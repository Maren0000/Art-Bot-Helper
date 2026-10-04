# art-bot-helper

Discord bot for sharing Pixiv and Twitter fan-art, with a FastAPI admin UI and a
userscript-facing API running in the same process.

## Layout

| Path | What it is |
| --- | --- |
| `main.py` | Entry point. Runs the discord.py bot and uvicorn concurrently. |
| `cogs/` | Discord commands, loaded dynamically at startup. |
| `web/` | Admin UI (`app.py`, session-cookie auth) and userscript API (`api.py`, bearer-token auth). |
| `services/`, `utils/` | Posting, tagging, Pixiv/Bluesky fetching, hashing. |
| `db/` | Tortoise ORM models over SQLite. |
| `userscript/` | The browser userscript that talks to `web/api.py`. |

## Configuration

Runtime secrets come from the environment; everything else comes from JSON files
in `CONFIG_PATH`, editable through the admin UI.

| Variable | Required | Notes |
| --- | --- | --- |
| `TOKEN` | yes | Discord bot token. |
| `CONFIG_PATH` | yes | Directory of config JSONs. `/config` in the image. |
| `SQLITE_PATH` | yes | DB file. `/data/artbot.db` in the image. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | yes | Admin UI login. A blank password makes the UI unusable, not open. |
| `WEB_SECRET` | recommended | Signs session cookies and userscript tokens. Falls back to `TOKEN` if unset, which ties token validity to the bot token. |
| `WEB_HOST` / `WEB_PORT` | in containers | Default `127.0.0.1:8000`; the image sets `0.0.0.0:8000`. |
| `PIXIV_COOKIE` | for Pixiv | `PHPSESSID` value. |
| `HF_TOKEN` | for tagging | Hugging Face token for the cl_tagger spaces. |
| `BLUESKY_IDENTIFIER` / `BLUESKY_APP_PASSWORD` | no | Bluesky support is skipped when either is blank. |
| `TASK_STATUS_CHANNEL_ID` | no | Channel the scheduled tasks report into. |
| `MODE` | no | `DEV` loads jishaku. |
| `WEB_COOKIE_SECURE` | no | `auto` (follow request scheme), `1`, or `0`. |
| `WEB_FORWARDED_ALLOW_IPS` | no | Proxies whose `X-Forwarded-*` headers are trusted. Default `*`. |
| `OIDC_*` | no | Single sign-on for the admin UI — see below. |

### OIDC single sign-on (optional)

The admin UI can authenticate against any OpenID Connect provider using the
Authorization Code flow with PKCE. It is **inert unless `OIDC_ISSUER`,
`OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` are all set**, so existing
deployments are unaffected.

The userscript API (`web/api.py`) keeps its own bearer-token auth and is
deliberately untouched — a userscript cannot perform a browser redirect.

| Variable | Default | Notes |
| --- | --- | --- |
| `OIDC_ISSUER` | — | Base URL. `/.well-known/openid-configuration` is discovered from it. |
| `OIDC_CLIENT_ID` | — | |
| `OIDC_CLIENT_SECRET` | — | |
| `OIDC_REDIRECT_URL` | derived | `https://<host>/auth/oidc/callback`. Set it explicitly. |
| `OIDC_PROVIDER_NAME` | `SSO` | Button label on the login page. |
| `OIDC_SCOPES` | `openid profile email` | Add your groups scope if the provider needs one. |
| `OIDC_ALLOWED_GROUPS` | — | Comma-separated. Case-insensitive. |
| `OIDC_ALLOWED_EMAILS` | — | Comma-separated. |
| `OIDC_ALLOWED_SUBS` | — | Comma-separated subject IDs. |
| `OIDC_GROUPS_CLAIM` | `groups` | Claim to read groups from. |
| `OIDC_USERNAME_CLAIM` | `preferred_username` | Falls back to `email`, then `sub`. |
| `OIDC_DISABLE_PASSWORD_LOGIN` | `0` | Turn on only after SSO works. |

**Restrict who can log in.** If `OIDC_ALLOWED_GROUPS`, `OIDC_ALLOWED_EMAILS`
and `OIDC_ALLOWED_SUBS` are all empty, *any* account your provider will
authenticate becomes a full admin of this panel. That is fine when the provider
only issues tokens to an application you have already restricted; it is
dangerous with a public IdP. A warning is logged at startup when no allow-list
is set.

Password login stays enabled alongside SSO so a provider outage cannot lock you
out. Set `OIDC_DISABLE_PASSWORD_LOGIN=1` once SSO is confirmed working — doing
so also invalidates any session that was issued via password.

Notes on the implementation:

- Claims come from the `userinfo` endpoint, so no ID token signature
  verification, no JWKS handling, and no new dependency. If a provider
  advertises no `userinfo` endpoint, the ID token's claims are read instead and
  `iss` / `aud` / `exp` / `nonce` are validated — permitted by OIDC Core 3.1.3.7
  because that token came straight from the token endpoint over TLS.
- CSRF `state`, the PKCE verifier and the post-login target live in a
  short-lived HMAC-signed cookie scoped to `/auth/oidc`. There is no
  server-side session store, so a restart does not break in-flight logins.
- Behind a reverse proxy, uvicorn runs with `proxy_headers` enabled so
  `request.url.scheme` is correct; otherwise cookies would never be marked
  `Secure` and a derived `redirect_uri` would come out as `http://`.

### How the character map is built

`char_map.json` is generated from Danbooru in two passes, because Danbooru only
appends a `(series)` qualifier to a character tag when the name would otherwise
be ambiguous.

1. **Qualified tags** — `elysia_(honkai_impact)`, `belle_(zenless_zone_zero)`.
   Matched by comparing the trailing parenthesised qualifier against
   `target_series.json`.
2. **Unqualified tags** — `kiana_kaslana`, `ellen_joe`, `hoshimi_miyabi`. These
   carry no series information at all, so membership is inferred from
   co-occurrence with the series' copyright tag via Danbooru's `related_tag`
   API. A tag is accepted at an `overlap_coefficient` of 0.5 or above with at
   least 20 posts; real members measure 0.93–1.0 while crossover appearances
   measure 0.001–0.14.

Pass 2 matters more than it sounds. For Zenless Zone Zero, 35 of the 60 most
common characters are unqualified, including the entire top of the roster.

**Put the qualifier in `target_series.json`, not the copyright tag.** They are
different namespaces and do not always agree:

| Series | Copyright tag | Character qualifier |
| --- | --- | --- |
| Zenless Zone Zero | `zenless_zone_zero` | `zenless_zone_zero` |
| Honkai Impact 3rd | `honkai_impact_3rd` | `honkai_impact` |

`honkai_impact` is not a Danbooru tag at all — it exists only inside character
names. Pass 1 matches on the qualifier, so `target_series.json` must hold
`honkai_impact`; pass 2 then resolves that to the copyright tag `honkai_impact_3rd`
automatically by probing a known character of the series. Listing both forms is
harmless if you are unsure.

Resolution deliberately prefers the *narrowest* copyright tag. Elysia scores
0.9998 against `honkai_(series)` and 0.9994 against `honkai_impact_3rd`, so
picking the strongest match alone would select the umbrella franchise and pull
the Star Rail cast into Honkai Impact.

### Anime forums are threaded by series

Gacha forums are named `{series}-{safety}` and hold a thread per character, an
"All Characters" thread, and group threads. Anime forums are named
`anime-{safety}` (`anime-art`, `anime-sus`) and hold **one thread per series**
with no "All Characters" thread. Any forum whose name starts with `anime-` is
treated this way.

`anime_map.json` maps a tag (Danbooru copyright tag from the tagger, or a Pixiv
tag such as `葬送のフリーレン`) to the series thread's exact name:

```json
{
  "sousou_no_frieren": "Frieren",
  "葬送のフリーレン": "Frieren"
}
```

When an image matches the Series Map, it goes to that gacha forum and the Anime
Map is ignored. A franchise with both a game and an anime belongs in whichever
map matches its original media. Characters are not used for anime posts, and a
missing series thread fails the post just as a missing character thread does.
Create it with `/thread create post` first.

### Webhooks are config, not environment

`webhooks.json` maps a forum channel name to a list of **Discord webhook URLs**,
and `services/posting.py` POSTs to those values directly. Earlier versions read a
single `WEBHOOK_PROXY` env var instead; the `WEBHOOK_*` environment variables are
no longer read by anything.

```json
{
  "channel-name": ["https://discord.com/api/webhooks/<id>/<token>"]
}
```

### Automatic character pulling is off until you configure it

`cogs/tasks.py` rebuilds `char_map.json` from Danbooru on a 10-day loop, and
`tasks.loop` fires its first iteration at startup rather than 10 days in. That
rebuild keeps a character tag only if its parenthesised series appears in
`target_series.json`, so on a fresh deploy with an empty config volume it would
scrape all of Danbooru's tags, aliases, and wiki pages for several minutes and
then write an empty `char_map.json` over whatever was there.

Both the scheduled task and `/update char_map_refresh` now refuse to run while
`target_series` is empty, before any HTTP happens. Populate **Configs → Target
Series** in the admin UI to turn automatic pulling on.

## Local development

```bash
cp .env.example .env   # then fill it in
docker compose up --build
```

`compose.yml` builds from source and bind-mounts the tree. It is for development
only — see the header of `docker-compose.portainer.yml`.

## Deployment

CI builds the image and Portainer pulls it; Portainer never builds. See
[docs/deployment.md](docs/deployment.md).
