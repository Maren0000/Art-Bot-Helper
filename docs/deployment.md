# Deployment

Same flow as `gw-viewer` and `xteink-site`: **Forgejo Actions builds and pushes
the image, then pokes a Portainer webhook. Portainer only ever pulls.**

```
push to main
  └─ .forgejo/workflows/build-image.yml
       ├─ check   byte-compile every module
       ├─ build   docker build → git.priv.maren.dev/maren/art-bot-helper:{sha,latest}
       ├─ push    both tags to the Forgejo container registry
       └─ POST    Portainer stack webhook  →  re-pull :latest, recreate container
```

## Why Portainer does not build

Portainer will not rebuild an image for a stack that uses `build:`. "Pull &
Redeploy" git-pulls the compose file and then reuses the cached image, even with
re-pull and force-redeploy both enabled (portainer/portainer#6288, #6897,
#11304, #12508). A push would look like it deployed and silently keep serving
the old code. So the image is built in CI and the stack references it by tag.

The webhook is fired as the **last** CI step. Wiring Forgejo's own push webhook
straight to Portainer would race the build and redeploy the previous image.

## One-time setup

Everything below is UI work — the API token used for automation is not the repo
owner and cannot enable Actions or write secrets.

### 1. Enable Actions on the repo

`Art-Bot-Helper` currently has the Actions unit disabled, so the workflow file is
inert. Settings → Units → tick **Actions** → Update.

Confirm the `linux-amd64` runner is visible under Settings → Actions → Runners.

### 2. Add the Actions secrets

Settings → Actions → Secrets:

| Secret | Value |
| --- | --- |
| `REGISTRY_USER` | Forgejo username that owns the package (`Maren`) |
| `REGISTRY_TOKEN` | Forgejo token with `write:package` scope |
| `PORTAINER_WEBHOOK_URL` | `https://docker.priv.maren.dev/api/stacks/webhooks/<uuid>` — from step 3 |

### 3. Create the Portainer stack

Stacks → Add stack → name `art-bot-helper`.

Use a **Repository** stack (like `gw-viewer`) so the compose file tracks the repo:

- Repository URL: `https://git.priv.maren.dev/Maren/Art-Bot-Helper`
- Reference: `refs/heads/main`
- Compose path: `docker-compose.portainer.yml` ← **not** `compose.yml`
- Authentication: on, with a Forgejo token that can read the repo (it is private)
- **GitOps updates → Webhook**: on. This generates the UUID for
  `PORTAINER_WEBHOOK_URL` above.

Then set the environment variables:

| Variable | Required | Notes |
| --- | --- | --- |
| `ABH_DISCORD_TOKEN` | yes | Discord bot token |
| `ABH_ADMIN_USER` | yes | Admin UI username |
| `ABH_ADMIN_PASS` | yes | Admin UI password |
| `ABH_WEB_SECRET` | yes | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ABH_PIXIV_COOKIE` | yes | Pixiv `PHPSESSID`; fetches 403 without it |
| `ABH_HF_TOKEN` | yes | Hugging Face token for the tagger spaces |
| `ABH_WEB_PORT` | no | Published port, default `8005` |
| `ABH_TAG` | no | Pin a commit sha; unset tracks `:latest` |
| `ABH_BSKY_ID` / `ABH_BSKY_PASS` | no | Bluesky; skipped when blank |
| `ABH_TASK_CHANNEL_ID` | no | Channel for scheduled-task reports |

Deploy. The first deploy pulls `:latest`, which only exists after the first
successful CI run — push to `main` (or run the workflow manually) first.

### 4. Populate the config volume

`abh-config` starts **empty**. The bot runs, but posting features that depend on
the maps will not match anything, and automatic character pulling stays disabled
by design (see the README). Log into the admin UI on `:8005` and upload or edit:

- `target_series.json` — **required to enable automatic character pulling**
- `series_map.json`, `safety_map.json`, `webhooks.json`
- `skip_tags.json`, `manual_overrides.json` as needed

`char_map.json` is generated from Danbooru once `target_series` is set.

### 5. Reverse proxy

Point a hostname (e.g. `artbot.priv.maren.dev`) at the Docker host's
`ABH_WEB_PORT`. The userscript and the admin UI share that origin.

## Volumes

| Volume | Mount | Contents |
| --- | --- | --- |
| `abh-config` | `/config` | Bot config JSONs, editable from the admin UI |
| `abh-data` | `/data` | `artbot.db` + WAL — every posted-image record, which duplicate detection depends on. **Back this up.** |

## Rollback

Set `ABH_TAG` to a commit sha in the stack's env and redeploy. Every CI run
pushes `:<sha>` alongside `:latest`.

## Build constraints

The runner's engine is rootful Podman behind its Docker-compatible API, which
implements the classic `/build` endpoint, not BuildKit — hence
`DOCKER_BUILDKIT=0`. Keep the Dockerfile free of heredoc `COPY`,
`--mount=type=cache`, and `--mount=type=secret`; the classic builder cannot parse
them and the build fails.

There is no separate `check` job. `actions/setup-python` cannot run on this
runner — it has no local tool cache and the version manifest is unreachable, so
it fails with *"The version '3.13' with architecture 'x64' was not found"*. The
syntax gate is a `compileall` step inside the Dockerfile instead: a SyntaxError
fails the build, so nothing is pushed and nothing is deployed. That also runs it
against the exact interpreter the container will use.

Every remaining pin ships a cp313 manylinux x86_64 wheel, so the image installs
no build toolchain. If you add a dependency without a wheel, install
`build-essential` in the **builder** stage only — never in the runtime stage.
