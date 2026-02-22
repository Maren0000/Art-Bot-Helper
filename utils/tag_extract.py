import json
import logging
import os
import re
import time
from pathlib import Path

import requests

from config import Config

LOGGER = logging.getLogger(__name__)

DANBOORU_BASE_URL = "https://danbooru.donmai.us/tags.json"
DANBOORU_ALIAS_URL = "https://danbooru.donmai.us/tag_aliases.json"
DANBOORU_WIKI_URL = "https://danbooru.donmai.us/wiki_pages.json"

FETCH_LIMIT = 1000
SLEEP_TIME = 0.1

DEFAULT_CONFIG_DIR = Path(
    os.getenv("CONFIG_PATH", str(Path(__file__).resolve().parents[1] / "configs"))
)
DEFAULT_OUTPUT_FILE = "char_map.json"

PAREN_RE = re.compile(r"\(([^)]+)\)")


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
        resp = requests.get(DANBOORU_BASE_URL, params=params, timeout=30)
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
        resp = requests.get(DANBOORU_ALIAS_URL, params=params, timeout=30)
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
        resp = requests.get(DANBOORU_WIKI_URL, params=params, timeout=30)
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

    aliases = fetch_all_tag_aliases()
    apply_aliases(mapping, aliases, skip_tags)

    wiki_pages = fetch_all_wiki_pages()
    apply_wiki_translations(mapping, wiki_pages)

    return mapping


def write_character_map(mapping: dict[str, str], output_file: Path) -> None:
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)


def run_update(
    config: Config,
    output_file: Path | None = None,
) -> int:
    output_file = output_file or (config.base_path / DEFAULT_OUTPUT_FILE)
    mapping = generate_character_map(config)
    write_character_map(mapping, output_file)
    LOGGER.info(f"Written {len(mapping)} entries to {output_file}")
    return len(mapping)


def main():
    config = Config(str(DEFAULT_CONFIG_DIR))
    run_update(config)


if __name__ == "__main__":
    main()
