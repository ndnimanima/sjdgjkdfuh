# روزنه · Rozaneh v1.06

**خبر، ویدیو و لینک را دریافت کن؛ هوشمندانه تحلیل کن؛ با کنترل کامل منتشر کن.**

GitHub Actions in `.github/workflows/ci.yml` checks Python/JavaScript/shell syntax, deployment-config parsing, API permissions and settings, Persian/Jalali date handling, Digiato-style article extraction, source-grounded summaries, image-generation fallback (mocked), photo-aware resends, Telegram message sizing, and a Docker image build on pushes and pull requests.

Rozaneh is a Persian-first, bilingual newsroom and content-automation studio. It collects RSS/Atom feeds and news pages, extracts article text and genuine source images, classifies stories, translates and publishes them to messaging channels. News posts use source-grounded, multi-sentence summaries, explain AI stories in context, fit within one platform message, and skip thin or headline-only source copy instead of adding filler. Publication dates—including Persian/Jalali dates and timezones—are verified before the 24-hour cutoff and shown as the source publication time. The focused Link & Video Analyzer prepares NotebookLM-like summaries, key points, optional deep analysis, and an editable channel draft.

> **Release:** `1.06` · Persian RTL + English LTR · Four themes: Aurora Dark, Cyber Obsidian, Persian Emerald, and Silk Daylight.

## Highlights

- **News sources:** RSS, Atom, JSON Feed, and ordinary HTML pages; full-article extraction; verified article images (prefer the article lead image over a feed thumbnail); per-source attribution (off by default), custom source label, and default topic.
- **News quality:** source-grounded multi-sentence summaries, extra context for AI stories, platform-aware one-message sizing, and a conservative quality gate that archives/skips headline-only or very thin source copy instead of inventing filler.
- **Topics & filtering:** Persian/English keyword matching, topic test lab, per-rule `all` / `smart` / `strict` modes, and exclude keywords.
- **Automation:** schedules or intervals, source/topic/destination selection, explanatory summaries, translation, genuine source photos, unseen-item protection, dry runs, and run reports. When photo delivery is enabled, a real article photo is preferred; a user-configured OpenAI-compatible image API can create a clearly illustrative fallback only when the source has no image.
- **Publication dates:** ISO, RFC, Persian digits, and Jalali dates are normalized in the configured timezone. Canonical article dates are checked before the item cap so old stories cannot enter the 24-hour feed or crowd out current news.
- **Panel layout:** navigation and top bar stay fixed while long content scrolls independently. Feed checks and destination tests update their rows/cards in place rather than resetting the panel.
- **Link & Video Analyzer:** compact, NotebookLM-like summaries and key points, collapsed transcript/deep analysis, editable channel draft, destination selection, and direct publishing. Configure a dedicated OpenAI-compatible analysis endpoint, model, and API key in the analyzer; credentials are not returned to the browser. Supports YouTube and other extractors available through `yt-dlp`, plus article/social URLs supported by installed extractors.
- **Archive:** search and status filters, image/message preview, source publication date, filter reasons, source link, and photo-aware manual publishing to selected destinations.
- **Channels:** Telegram, Bale, Eitaa, Rubika, and HTTPS webhooks, with per-platform limits and connection tests.
- **Creators & learning:** co-founders Nima Dalir and Alireza Bokharaei, plus the NextGen AI / n8n YouTube and Telegram channels. Creator/team profiles are read-only in the panel.
- **Admin:** Persian/English interface, four saved themes behind a compact palette button, translation provider settings, JSON backup/restore, logs, sessions, and runtime diagnostics.

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

Open `http://localhost:8080`; Compose persists data in the `rozaneh_data` volume. Back up that volume or `/data/rozaneh.db` regularly; include `/data/generated_images` if you use generated illustrations.

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

Translation provider credentials can be configured in the authenticated panel. The analyzer has separate OpenAI-compatible chat-completions settings (endpoint, model, and key); optional image-generation settings are also available there and are disabled until explicitly enabled. Generated illustrations are cached under `DATA_DIR/generated_images`, so that directory must share the app's persistent volume. Never commit `.env`, bot tokens, API keys, or a production database.

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

Run the offline content tests directly (they use temporary data and make no network calls):

```bash
python docs/news_quality_smoke.py
python docs/pipeline_quality_smoke.py
python docs/pipeline_delivery_smoke.py
python docs/date_parser_smoke.py
python docs/imagegen_smoke.py
python docs/api_smoke.py
```

In another shell (Playwright and Chromium must be installed):

```bash
DATA_DIR=/tmp/rozaneh-smoke python docs/smoke_ui.py
python docs/verify_panel.py --base http://127.0.0.1:8080
python docs/login_check.py --base http://127.0.0.1:8080 --engines chromium
```

The browser smoke test creates and removes temporary feeds, topics, destinations, and jobs; it seeds one synthetic archive row in the disposable database to test preview. It exercises CRUD, topic matching, channel rules, scheduling, translation, archive preview, settings, and admin tools. `news_quality_smoke.py` and `pipeline_quality_smoke.py` verify source-grounded summaries, weak-story filtering, image retention, and Telegram caption sizing without external services. `verify_panel.py` checks all routes, responsive widths, and the fixed-navigation/internal-scroll behavior; `login_check.py` probes the sign-in layout in Persian and English. A few browser checks need outbound access to the test feed URL and translation service. Jobs run in dry-run mode and no channel post is sent.

## License

MIT. See [`LICENSE`](LICENSE) if included in the repository.

---

## English summary

Rozaneh v1.06 is a self-hostable bilingual (Persian RTL / English LTR) newsroom and media automation panel. It produces source-grounded single-message news summaries, verifies Jalali and timezone-aware publication dates, prefers genuine article photos, and can optionally generate an illustration when no source photo exists. The compact analyzer supports a dedicated OpenAI-compatible analysis API, key-point summaries, optional deep detail, and an editable channel draft. Keep its database and generated-image cache on persistent writable storage; Cloudflare Workers are only an optional HTTPS edge proxy, not the Python runtime.
