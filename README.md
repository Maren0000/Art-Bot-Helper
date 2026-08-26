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
