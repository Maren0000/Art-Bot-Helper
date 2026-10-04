import json
import logging
import os
import re
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config

LOGGER = logging.getLogger(__name__)

DANBOORU_BASE_URL = "https://danbooru.donmai.us/tags.json"
DANBOORU_ALIAS_URL = "https://danbooru.donmai.us/tag_aliases.json"
DANBOORU_WIKI_URL = "https://danbooru.donmai.us/wiki_pages.json"
DANBOORU_RELATED_URL = "https://danbooru.donmai.us/related_tag.json"
DANBOORU_TAGS_LOOKUP_URL = "https://danbooru.donmai.us/tags.json"

CATEGORY_COPYRIGHT = 3
CATEGORY_CHARACTER = 4

USER_AGENT = "Art-Bot-Helper/1.0"

# Danbooru intermittently answers 500/502/503 under load, and a full rebuild
# makes hundreds of paginated requests, so a single transient failure used to
# throw away the whole run. Retry those (and dropped connections / read
# timeouts) with exponential backoff -- 0s, 2s, 4s, 8s, 16s -- honouring
# Retry-After on 429/503. raise_on_status=False hands the final response back
# so callers' raise_for_status() still reports the real status once retries
# run out.
DANBOORU_RETRY = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})
SESSION.mount("https://", HTTPAdapter(max_retries=DANBOORU_RETRY))

FETCH_LIMIT = 1000
SLEEP_TIME = 0.1

# Thresholds for the unqualified-character pass (see fetch_series_characters).
# Danbooru only appends a "(series)" qualifier to a character tag when the name
# would otherwise be ambiguous, so most characters with a distinctive name --
# kiana_kaslana, ellen_joe, hoshimi_miyabi -- carry no series at all. Those tags
# have nothing to match on, so membership is inferred from co-occurrence with
# the series' copyright tag instead.
#
# overlap_coefficient is |A n B| / min(|A|, |B|): 1.0 means every post with the
# character is also tagged with this series. Real members measure 0.93-1.0;
# crossover appearances from other franchises measure 0.001-0.14, so the gap is
# wide and 0.5 sits comfortably in it. The post floor exists because a tag with
# two posts that happen to be crossovers also scores 1.0.
UNQUALIFIED_MIN_OVERLAP = 0.5
UNQUALIFIED_MIN_POSTS = 20
# A character sits inside several nested copyright tags at once. Elysia scores
# 0.9998 against honkai_(series) and 0.9994 against honkai_impact_3rd, so
# "highest overlap" picks the umbrella franchise and drags in Star Rail. Treat
# anything above this as a match and then take the most specific one.
COPYRIGHT_MIN_OVERLAP = 0.9
RELATED_LIMIT = 1000

DEFAULT_CONFIG_DIR = Path(
    os.getenv("CONFIG_PATH", str(Path(__file__).resolve().parents[1] / "configs"))
)
DEFAULT_OUTPUT_FILE = "char_map.json"

PAREN_RE = re.compile(r"\(([^)]+)\)")


class ConfigNotReady(RuntimeError):
    """Raised when the character map cannot be rebuilt because configs are unset.

    build_mapping() keeps a Danbooru character tag only if its trailing
    parenthesised series is in config.target_series. An empty target_series
    therefore matches nothing, and run_update() would happily write an empty
    char_map.json over a good one after several minutes of scraping. Fail
    loudly and early instead -- see the guard in run_update().
    """


def fetch_all_character_tags():
    all_tags = []
    page = 1

    while True:
        params = {
            "search[category]": 4,
            "limit": FETCH_LIMIT,
            "page": page,
        }

        #LOGGER.info(f"Fetching Danbooru page {page}...")
        resp = SESSION.get(DANBOORU_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if not data:
            break

        all_tags.extend(data)

        if len(data) < FETCH_LIMIT:
            break

        page += 1
        time.sleep(SLEEP_TIME)

    LOGGER.info(f"Fetched {len(all_tags)} character tags total")
    return all_tags


def fetch_all_tag_aliases():
    aliases = []
    page = 1

    while True:
        params = {
            "search[status]": "active",
            "limit": FETCH_LIMIT,
            "page": page,
        }

        #LOGGER.info(f"Fetching Danbooru aliases page {page}...")
        resp = SESSION.get(DANBOORU_ALIAS_URL, params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if not data:
            break

        aliases.extend(data)

        if len(data) < FETCH_LIMIT:
            break

        page += 1
        time.sleep(SLEEP_TIME)

    LOGGER.info(f"Fetched {len(aliases)} aliases total")
    return aliases


def fetch_all_wiki_pages():
    pages = []
    page = 1

    while True:
        params = {
            "limit": FETCH_LIMIT,
            "page": page,
        }

        #LOGGER.info(f"Fetching Danbooru wiki page {page}...")
        resp = SESSION.get(DANBOORU_WIKI_URL, params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if not data:
            break

        pages.extend(data)

        if len(data) < FETCH_LIMIT:
            break

        page += 1
        time.sleep(SLEEP_TIME)

    LOGGER.info(f"Fetched {len(pages)} wiki pages total")
    return pages


def _get_json(url: str, params: dict):
    resp = SESSION.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def resolve_copyright_tag(qualifier: str, example_tag: str | None = None) -> str | None:
    """Map a target_series entry to the Danbooru copyright tag it refers to.

    These are two different namespaces and they do not always agree. The
    copyright tag for Honkai Impact 3rd is `honkai_impact_3rd`, but its
    characters are qualified `elysia_(honkai_impact)` -- and `honkai_impact` is
    not a tag at all, it returns post_count 0. target_series holds the
    QUALIFIER, because that is what is matched against character names, so we
    have to find the copyright tag before we can ask which characters belong
    to it.

    First try the entry as a copyright tag directly (true for
    zenless_zone_zero, blue_archive, ...). Failing that, take a known character
    of the series and ask which copyright it co-occurs with most.
    """
    try:
        found = _get_json(DANBOORU_TAGS_LOOKUP_URL,
                          {"search[name]": qualifier, "search[category]": CATEGORY_COPYRIGHT})
        if found and found[0].get("post_count", 0) > 0:
            return found[0]["name"]
    except Exception as e:
        LOGGER.debug("Copyright lookup for %s failed: %s", qualifier, e)

    if not example_tag:
        return None
    try:
        data = _get_json(DANBOORU_RELATED_URL,
                         {"query": example_tag, "category": CATEGORY_COPYRIGHT, "limit": 5})
    except Exception as e:
        LOGGER.warning("Could not resolve a copyright tag for %s: %s", qualifier, e)
        return None

    candidates = []
    for entry in data.get("related_tags", []):
        tag = entry.get("tag") or {}
        if tag.get("category") != CATEGORY_COPYRIGHT:
            continue
        candidates.append((tag.get("name", ""), tag.get("post_count", 0),
                           entry.get("overlap_coefficient") or 0))
    if not candidates:
        return None

    strong = [c for c in candidates if c[2] >= COPYRIGHT_MIN_OVERLAP]
    if strong:
        # Smallest post count = narrowest tag. honkai_(series) spans 187k posts
        # across the whole franchise; honkai_impact_3rd spans 53k and is the one
        # whose cast we actually want.
        name = min(strong, key=lambda c: c[1])[0]
    else:
        name = max(candidates, key=lambda c: c[2])[0]

    LOGGER.info("Resolved target series %s -> copyright tag %s", qualifier, name)
    return name


def fetch_series_characters(copyright_tag: str) -> list[str]:
    """Character tags WITHOUT a series qualifier that belong to this series.

    Qualified tags are deliberately excluded here: their qualifier already says
    which series they belong to, build_mapping() handles them, and trusting
    co-occurrence for them would wrongly pull in crossovers such as
    wolfie_(fortnite), whose two posts are both Zenless crossovers and so
    scores an overlap of 1.0.
    """
    try:
        data = _get_json(DANBOORU_RELATED_URL,
                         {"query": copyright_tag, "category": CATEGORY_CHARACTER,
                          "limit": RELATED_LIMIT})
    except Exception as e:
        LOGGER.warning("Could not fetch characters for %s: %s", copyright_tag, e)
        return []

    names = []
    for entry in data.get("related_tags", []):
        tag = entry.get("tag") or {}
        name = tag.get("name") or ""
        if tag.get("category") != CATEGORY_CHARACTER or not name or "(" in name:
            continue
        if tag.get("post_count", 0) < UNQUALIFIED_MIN_POSTS:
            continue
        if (entry.get("overlap_coefficient") or 0) < UNQUALIFIED_MIN_OVERLAP:
            continue
        names.append(name)
    return names


def add_unqualified_characters(mapping, config: Config, tags) -> int:
    """Second pass: characters whose tag carries no series qualifier."""
    examples: dict[str, tuple[str, int]] = {}
    for tag in tags:
        name = tag.get("name") or ""
        parts = extract_parentheses(name)
        if not parts:
            continue
        series = parts[-1]
        if series not in config.target_series:
            continue
        # Highest post count makes the most reliable probe for the copyright.
        count = tag.get("post_count", 0)
        if series not in examples or count > examples[series][1]:
            examples[series] = (name, count)

    added = 0
    for series in sorted(config.target_series):
        example = examples.get(series, (None, 0))[0]
        copyright_tag = resolve_copyright_tag(series, example)
        if not copyright_tag:
            LOGGER.warning(
                "Skipping unqualified characters for %s: no copyright tag found. "
                "Check that it is spelled as Danbooru spells it.", series
            )
            continue
        for name in fetch_series_characters(copyright_tag):
            if name in config.skip_tags or name in mapping:
                continue
            if name in config.manual_overrides:
                mapping[name] = config.manual_overrides[name]
            else:
                mapping[name] = prettify_name(name)
            added += 1
        time.sleep(SLEEP_TIME)

    LOGGER.info("Added %d unqualified character mappings", added)
    return added


def extract_parentheses(tag_name: str):
    return PAREN_RE.findall(tag_name)


def strip_parentheses(tag_name: str):
    return re.sub(r"\s*\([^)]*\)", "", tag_name)


def is_target_series(tag_name: str, target_series: set[str]) -> bool:
    parts = extract_parentheses(tag_name)
    return bool(parts) and parts[-1] in target_series


def get_base_character_name(tag_name: str):
    return strip_parentheses(tag_name).strip("_")


def prettify_name(raw: str):
    return " ".join(word.capitalize() for word in raw.strip().split("_"))


def is_valid_alt_name(name: str) -> bool:
    if not name:
        return False
    if len(name) > 50:
        return False
    if "/" in name or "," in name or ";" in name:
        return False
    if name.lower().startswith("see "):
        return False
    return True


def build_mapping(
    tags, target_series: set[str], skip_tags: set[str], manual_overrides: dict[str, str]
):
    result = {}

    for tag in tags:
        name = tag.get("name")

        if name in skip_tags:
            continue

        if name in manual_overrides:
            result[name] = manual_overrides[name]
            continue

        base_name = get_base_character_name(name)

        if not is_target_series(name, target_series):
            continue

        result[name] = prettify_name(base_name)

    return result


def apply_aliases(mapping, aliases, skip_tags: set[str]):
    added = 0

    for alias in aliases:
        antecedent = alias.get("antecedent_name")
        consequent = alias.get("consequent_name")

        if not antecedent or not consequent:
            continue
        if antecedent in skip_tags:
            continue
        if antecedent in mapping:
            continue

        final_name = mapping.get(consequent)
        if not final_name:
            continue

        mapping[antecedent] = final_name
        added += 1

    LOGGER.info(f"Added {added} alias mappings")


def apply_wiki_translations(mapping, wiki_pages):
    added = 0

    for wiki in wiki_pages:
        if wiki.get("is_deleted"):
            continue

        title = wiki.get("title")
        if not title:
            continue

        final_name = mapping.get(title)
        if not final_name:
            continue

        translated = wiki.get("translated_name")
        if translated and is_valid_alt_name(translated):
            if translated not in mapping:
                mapping[translated] = final_name
                added += 1

        for alt in wiki.get("other_names", []):
            if not is_valid_alt_name(alt):
                continue
            if alt in mapping:
                continue

            mapping[alt] = final_name
            added += 1

    LOGGER.info(f"Added {added} wiki translation mappings")


def generate_character_map(config: Config) -> dict[str, str]:
    target_series = config.target_series
    skip_tags = config.skip_tags
    manual_overrides = config.manual_overrides

    tags = fetch_all_character_tags()
    mapping = build_mapping(tags, target_series, skip_tags, manual_overrides)

    # build_mapping() can only match tags that carry a "(series)" qualifier.
    # Danbooru omits it whenever a character's name is already unambiguous, so
    # on its own the pass above silently drops most of a series' cast.
    add_unqualified_characters(mapping, config, tags)

    aliases = fetch_all_tag_aliases()
    apply_aliases(mapping, aliases, skip_tags)

    wiki_pages = fetch_all_wiki_pages()
    apply_wiki_translations(mapping, wiki_pages)

    return mapping


def write_character_map(mapping: dict[str, str], output_file: Path) -> None:
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)


def config_ready(config: Config) -> bool:
    """Whether there is enough config for a rebuild to produce anything."""
    return bool(config.target_series)


def run_update(
    config: Config,
    output_file: Path | None = None,
) -> int:
    # Refuse before scraping, not after. Without target_series every fetched
    # tag is filtered out, so the run costs several minutes of Danbooru
    # requests and then truncates char_map.json to {}. Populate
    # target_series.json in the web UI (Configs -> Target Series) first.
    if not config_ready(config):
        raise ConfigNotReady(
            f"target_series is empty ({config.base_path / 'target_series.json'}); "
            "set it up in the web UI before refreshing the character map"
        )

    output_file = output_file or (config.base_path / DEFAULT_OUTPUT_FILE)
    mapping = generate_character_map(config)
    write_character_map(mapping, output_file)
    LOGGER.info(f"Written {len(mapping)} entries to {output_file}")
    return len(mapping)


def main():
    logging.basicConfig(level=logging.INFO)
    config = Config(str(DEFAULT_CONFIG_DIR))
    try:
        run_update(config)
    except ConfigNotReady as e:
        raise SystemExit(f"Refusing to rebuild the character map: {e}")


if __name__ == "__main__":
    main()
