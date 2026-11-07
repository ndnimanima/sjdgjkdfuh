# روزنه · Rozaneh v1.04

**خبر، ویدیو و لینک را دریافت کن؛ هوشمندانه تحلیل کن؛ با کنترل کامل منتشر کن.**

GitHub Actions in `.github/workflows/ci.yml` checks Python/JavaScript/shell syntax, deployment-config parsing, an isolated API smoke test, and a Docker image build on pushes and pull requests.

Rozaneh is a Persian-first, bilingual newsroom and content-automation studio. It collects RSS/Atom feeds and news pages, extracts article text and images, classifies stories, translates and publishes them to messaging channels. The Link & Video Analyzer also extracts and summarizes supported web and social-media content and prepares an editable channel draft.

> **Release:** `1.04` · Persian RTL + English LTR · Four themes: Aurora Dark, Cyber Obsidian, Persian Emerald, and Silk Daylight.

## Highlights

- **News sources:** RSS, Atom, JSON Feed, and ordinary HTML pages; optional full-article extraction, real article images, per-source attribution (off by default), custom source label, and default topic.
- **Topics & filtering:** Persian/English keyword matching, topic test lab, per-rule `all` / `smart` / `strict` modes, and exclude keywords.
- **Automation:** schedules or intervals, source/topic/destination selection, full text, translation, image, unseen-item protection, dry runs, and run reports.
- **Link & Video Analyzer:** background extraction with live status polling, summaries, key points, deeper analysis, editable channel draft, destination selection, and direct publishing. Supports YouTube and other extractors available through `yt-dlp`, plus article/social URLs supported by the installed extractors.
- **Archive:** search and status filters, image/message preview, filter reasons, source link, and manual publishing to selected destinations.
- **Channels:** Telegram, Bale, Eitaa, Rubika, and HTTPS webhooks, with per-platform limits and connection tests.
- **Creators & learning:** co-founders Nima Dalir and Alireza Bokharaei, plus the NextGen AI / n8n YouTube and Telegram channels.
- **Admin:** Persian/English interface, four saved themes, translation provider settings, JSON backup/restore, logs, sessions, and runtime diagnostics.

## Quick start

### Local Python

```bash
cp .env.example .env
# Set a strong ADMIN_PASSWORD in .env before exposing the app.
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`. The first-run password is the `ADMIN_PASSWORD` value in `.env` (default in the application code is `rozaneh` if no value is supplied). Change it after signing in. The default database is `./data/rozaneh.db`.

### Docker Compose (persistent local install)

```bash
cp .env.example .env
# Edit ADMIN_PASSWORD and, for HTTPS, set COOKIE_SECURE=1.
docker compose up -d --build
```

Open `http://localhost:8080`; Compose persists data in the `rozaneh_data` volume. Back up that volume or `/data/rozaneh.db` regularly.

### Deployment guides

- **Railway, Render, Fly.io, Docker/VPS, Cloudflare edge proxy, backups, and checks:** [`docs/DEPLOY.md`](docs/DEPLOY.md)
- **Clean GitHub source upload and history safety:** [`docs/GITHUB_UPLOAD.md`](docs/GITHUB_UPLOAD.md)
- **Railway:** `railway.toml` and `Dockerfile`
- **Render:** `render.yaml` (attach the persistent disk at `/data`)
- **Fly.io:** `fly.toml` (create a volume and set `ADMIN_PASSWORD` with `fly secrets`)
- **Cloudflare Workers:** `wrangler.toml` + `cloudflare/worker.js` proxy traffic to a separately hosted FastAPI origin. Cloudflare Workers do not host this Python/SQLite scheduler directly.
- **Ubuntu/Debian VPS:** `start.sh` installs a systemd service.

Every production deployment needs **persistent writable storage** mounted at `DATA_DIR`; without it the SQLite database, sessions, configuration, and archive will be lost on replacement. Run one scheduler-enabled application instance unless you have explicitly designed a distributed scheduler.

## Configuration

See [`.env.example`](.env.example). Main variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_PASSWORD` | `rozaneh` | Bootstrap password, used only until changed in the panel. `ROZANEH_PASSWORD` is accepted as an alias. |
| `DATA_DIR` | `./data` | Directory for persistent SQLite data. Use `/data` on hosted platforms with a mounted disk. |
| `PORT` | `8080` | HTTP port injected by the host or used locally. |
| `DEFAULT_TZ` | `Asia/Tehran` | Timezone for scheduled jobs. |
| `COOKIE_SECURE` | `0` | Set to `1` when serving the panel over HTTPS. |
| `SCHEDULER_ENABLED` | `1` | Set to `0` for an API/UI instance that must not run the scheduler. |
| `SESSION_DAYS` | `7` | Admin session lifetime. |
| `HTTP_TIMEOUT` | `22` | Outgoing network timeout in seconds. |
| `TICK_SECONDS` | `15` | Scheduler check cadence. |
| `SEND_DELAY` | `0.8` | Delay between channel sends. |

Translation provider credentials can be configured in the authenticated panel. Never commit `.env`, bot tokens, API keys, or a production database.

## Useful endpoints

- `GET /healthz` — liveness check.
- `GET /api/meta` — version, theme, language, platform, and runtime metadata.
- `GET /api/dashboard` — KPIs, activity, upcoming rules, recent news and analysis.
- `GET/POST/PATCH /api/feeds` — source configuration.
- `GET/POST/PATCH /api/jobs` — schedules and smart-filter settings.
- `GET/POST /api/analyzer` and `GET /api/analyzer/{id}` — analyzer queue and polling.
- `POST /api/analyzer/{id}/publish` — publish an approved analysis to selected channels.
- `GET /api/items` and `POST /api/items/{id}/resend` — archive and manual publishing.

All `/api/*` administration and mutation endpoints require an authenticated session.

## Development and smoke test

For local development, export `.env` before starting Uvicorn (it does not load `.env` automatically):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

For the Playwright smoke test, use a separate disposable database and disable the scheduler:

```bash
mkdir -p /tmp/rozaneh-smoke
DATA_DIR=/tmp/rozaneh-smoke ADMIN_PASSWORD=rozaneh COOKIE_SECURE=0 SCHEDULER_ENABLED=0 \
  uvicorn app.main:app --host 0.0.0.0 --port 8080
```

In another shell (Playwright and Chromium must be installed):

```bash
DATA_DIR=/tmp/rozaneh-smoke python docs/smoke_ui.py
python docs/verify_panel.py --base http://127.0.0.1:8080
python docs/login_check.py --base http://127.0.0.1:8080 --engines chromium
```

The main test creates and removes temporary feeds, topics, destinations, and jobs; it seeds one synthetic archive row in the disposable database to test preview. It exercises CRUD, topic matching, channel rules, scheduling, translation, archive preview, settings, and admin tools. `verify_panel.py` checks all routes and responsive widths; `login_check.py` probes the sign-in layout in Persian and English. A few checks need outbound access to the test feed URL and translation service. Jobs run in dry-run mode and no channel post is sent.

## License

MIT. See [`LICENSE`](LICENSE) if included in the repository.

---

## English summary

Rozaneh v1.04 is a self-hostable bilingual (Persian RTL / English LTR) news and media automation panel. It combines scheduled feed ingestion, full-article and image extraction, topic-aware filtering, translation, multi-platform publishing, an asynchronous link/video analyzer, an editable publish workflow, and a searchable archive with filter explanations. Deploy the Python app on a persistent container/VPS platform; Cloudflare Workers are provided as an optional HTTPS edge proxy, not as the application runtime.
