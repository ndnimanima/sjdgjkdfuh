# Rozaneh v1.06 — deployment guide

This guide covers persistent deployment of the Python application, HTTPS, first login, Cloudflare edge proxying, backups, and health checks.

> **Important architecture note:** Rozaneh uses FastAPI, a local SQLite database, background extraction tasks, and an in-process scheduler. Deploy the application on a persistent container/VPS platform with a writable disk. The Cloudflare Worker in this repository is an optional reverse proxy; it does **not** run the Python application or replace its persistent disk.

## 1. Production checklist

Before exposing a panel publicly:

1. Set a unique, strong `ADMIN_PASSWORD` (or `ROZANEH_PASSWORD`).
2. Mount persistent writable storage at `DATA_DIR` (usually `/data`).
3. Set `COOKIE_SECURE=1` when users access the panel over HTTPS.
4. Keep one scheduler-enabled app instance. Multiple replicas each run their own scheduler and can duplicate sends.
5. Use HTTPS; avoid publishing the admin port directly to the public internet without a TLS proxy.
6. Back up `/data/rozaneh.db` and, if you use AI-generated fallback images, `/data/generated_images`. Restrict access to backups; the database contains configuration and messaging credentials.

Common production variables:

```env
ADMIN_PASSWORD=replace-with-a-long-unique-password
DATA_DIR=/data
DEFAULT_TZ=Asia/Tehran
COOKIE_SECURE=1
SCHEDULER_ENABLED=1
PORT=8080
```

## 2. Railway

1. Push or fork this repository, then create a Railway project from the GitHub repository.
2. Railway builds the included `Dockerfile`.
3. Add a persistent **Volume** mounted at `/data`.
4. Add variables in Railway:
   - `DATA_DIR=/data`
   - `ADMIN_PASSWORD=<strong unique value>`
   - `DEFAULT_TZ=Asia/Tehran`
   - `COOKIE_SECURE=1`
   - `SCHEDULER_ENABLED=1`
5. Generate a public HTTPS domain. Railway injects `PORT`; the container binds to `0.0.0.0` and uses it.
6. Open the generated domain, sign in, then change the password in **Settings → Security**.
7. Verify `https://YOUR-DOMAIN/healthz` returns JSON with `"ok": true` and version `1.06`.

`railway.toml` points Railway to the Dockerfile and health endpoint. Do not scale to multiple scheduler-enabled replicas unless you first add a distributed scheduler/locking strategy.

## 3. Render

The repository includes a Render Blueprint in `render.yaml`.

1. In Render, choose **New → Blueprint** and select this repository.
2. When prompted, set the secret `ADMIN_PASSWORD` to a strong value.
3. Confirm the persistent disk is mounted at `/data` and `DATA_DIR=/data`.
4. Deploy and open the generated HTTPS URL. `COOKIE_SECURE=1` is set by the blueprint.
5. Confirm `/healthz`, sign in, and change the bootstrap password.

The included blueprint requests a 1 GB persistent disk. Check your Render plan/region for current disk availability and pricing before deployment.

## 4. Fly.io

The included `fly.toml` is a template; edit its `app` name to a globally unique value first.

```bash
fly auth login
# Edit fly.toml: app = "your-unique-rozaneh-name"
fly apps create your-unique-rozaneh-name
# Create the named volume in the same region as the app (default template: sjc).
fly volumes create rozaneh_data --region sjc --size 1
fly secrets set ADMIN_PASSWORD='use-a-long-unique-password'
fly deploy
fly status
```

The volume is mounted at `/data`. The configuration keeps one machine running because scheduled jobs must remain active. Confirm the app URL's `/healthz` endpoint after deploy. If you change `primary_region`, create the volume in that region too.

## 5. Docker / Docker Compose

### Compose

```bash
cp .env.example .env
# Edit .env; set a strong ADMIN_PASSWORD.
docker compose up -d --build
docker compose logs -f rozaneh
curl -fsS http://localhost:8080/healthz
```

Compose creates a named volume called `rozaneh_data`. To use another host port, set `HOST_PORT=8088` before `docker compose up`.

### Plain Docker

```bash
docker build -t rozaneh:1.06 .
docker volume create rozaneh_data
docker run -d --name rozaneh --restart unless-stopped \
  -p 8080:8080 -v rozaneh_data:/data \
  -e DATA_DIR=/data -e PORT=8080 \
  -e ADMIN_PASSWORD='use-a-long-unique-password' \
  -e DEFAULT_TZ=Asia/Tehran -e COOKIE_SECURE=0 \
  rozaneh:1.06
```

For a public HTTPS deployment behind a reverse proxy, use `COOKIE_SECURE=1`; keep the app port private to the proxy when possible.

## 6. Ubuntu/Debian VPS

The helper installs Python, creates a virtual environment, generates a random initial password if one is not supplied, and installs a systemd service. It defaults to the repository URL in this project:

```bash
curl -fsSL https://raw.githubusercontent.com/ndnimanima/uityy/main/start.sh | sudo bash
```

Optional overrides can be exported before running the script, for example:

```bash
sudo env ROZANEH_DIR=/opt/rozaneh \
  ROZANEH_PORT=8080 COOKIE_SECURE=0 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/ndnimanima/uityy/main/start.sh)"
```

The script writes the first password to `/opt/rozaneh/.env` (mode `0600`), keeps the database under `/opt/rozaneh/data`, and installs the `rozaneh` systemd unit. Put the VPS behind Nginx/Caddy/another HTTPS proxy and set `COOKIE_SECURE=1` in the environment file:

```bash
sudoedit /opt/rozaneh/.env  # set COOKIE_SECURE=1
sudo systemctl restart rozaneh
sudo systemctl status rozaneh
sudo journalctl -u rozaneh -f
```

A typical Nginx proxy must pass `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto`. Uvicorn is started with proxy-header support.

## 7. Cloudflare Worker edge proxy (optional)

The Cloudflare Worker can provide an edge hostname/TLS endpoint in front of an already-running FastAPI origin. The origin remains responsible for SQLite, scheduled jobs, media downloads, and persistent storage.

1. Deploy the FastAPI app using Railway, Render, Fly.io, Docker/VPS, or another persistent host.
2. Ensure the origin works directly over HTTPS and `/healthz` returns `ok: true`.
3. Edit `wrangler.toml` and set `ROZANEH_ORIGIN` to the origin's HTTPS base URL, with no trailing API path. Alternatively set it as a Worker variable in the Cloudflare dashboard.
4. Install Wrangler and deploy:

   ```bash
   npx wrangler login
   npx wrangler deploy
   ```

5. Open the Worker URL. Login cookies and API requests are forwarded without edge caching. Keep `COOKIE_SECURE=1` on the origin when the browser-facing Worker hostname uses HTTPS.
6. For a custom hostname, add a Worker route or custom domain in Cloudflare and point it to the deployed Worker.

### Optional D1 edge diagnostics

D1 is **not** the Rozaneh application database. The Worker can optionally insert path/method/status-only request diagnostics (no cookies, query strings, request bodies, or credentials):

```bash
npx wrangler d1 create rozaneh-edge
```

Copy the returned `database_id` into the commented D1 binding in `wrangler.toml`, uncomment it, then initialize the table:

```bash
npx wrangler d1 execute rozaneh-edge --remote --file=cloudflare/schema.sql
```

Set `LOG_EDGE_ACCESS="1"` in the Worker vars to enable logging. Leave it off if edge diagnostics are not needed; the core application does not depend on D1.

## 8. Local run and verification

For an ordinary development run, `.env` must be exported into the shell (Uvicorn does not load it automatically):

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

For the browser smoke test, start a **separate disposable instance** with the test password and scheduler disabled:

```bash
mkdir -p /tmp/rozaneh-smoke
DATA_DIR=/tmp/rozaneh-smoke ADMIN_PASSWORD=rozaneh COOKIE_SECURE=0 SCHEDULER_ENABLED=0 \
  uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Run the offline news-summary, pipeline, and API tests first. Then use Playwright and Chromium for the browser checks:

```bash
python docs/news_quality_smoke.py
python docs/pipeline_quality_smoke.py
python docs/api_smoke.py
DATA_DIR=/tmp/rozaneh-smoke python docs/smoke_ui.py
python docs/verify_panel.py --base http://127.0.0.1:8080
python docs/login_check.py --base http://127.0.0.1:8080 --engines chromium
```

The offline news tests verify extractive multi-sentence summaries, filtering of thin source copy, and photo-caption sizing; the API test uses a temporary database. The browser smoke test signs in with `rozaneh`, exercises feed/topic/channel/job CRUD, archive filtering and preview, translation, settings, and export. `verify_panel.py` checks all panel routes and responsive layouts (320–1440 px), including the fixed menu and internal content scroll; `login_check.py` probes the sign-in layout in Persian and English. The browser test removes the temporary entities it creates and seeds one synthetic archive row directly into the disposable SQLite database because the app has no public create-item route. A few browser checks require outbound access to the test feed URL and translation service; jobs run in dry-run mode and never send a channel post. Do not run it against production or a database with valuable state.

## 9. Backups and upgrades

- Back up `/data/rozaneh.db` on a schedule, and keep backups encrypted and access-controlled.
- The panel's JSON export is useful for configuration migration, but it is not a replacement for a full database backup.
- Keep an off-host copy of the database before upgrades. Mount the same persistent volume after rebuilding the image.
- Make sure only one active app instance runs the scheduler while testing upgrades.
- Do not commit `.env`, SQLite files, translation keys, bot tokens, or exported backups. `.gitignore` excludes local runtime data.

## 10. Troubleshooting

| Symptom | Likely cause / check |
| --- | --- |
| Login succeeds but refresh returns to login | Use HTTPS and set `COOKIE_SECURE=1`; verify the proxy forwards cookies and `X-Forwarded-Proto`. |
| Database `readonly` or `unable to open` | Confirm the mounted disk exists, `DATA_DIR` points to it, and the process can write there. The Docker entrypoint fixes ownership for mounted volumes. |
| Schedule runs twice | More than one scheduler-enabled replica is active. Scale to one instance or use a distributed lock/scheduler. |
| `/healthz` fails | Check container logs, `PORT`, startup command, and platform health-check path. |
| Feed/media extraction times out | Check outbound DNS/network access and increase `HTTP_TIMEOUT` if appropriate. Some source sites block cloud IPs. |
| Telegram rejects posts | Verify the bot token, chat ID, bot admin permissions, and channel test result in the panel. |
| Worker returns 502/503 | Check `ROZANEH_ORIGIN`, origin HTTPS certificate, origin health, and worker logs. The Worker cannot make a stopped/private origin reachable on its own. |
| Worker hostname does not sign in | Keep both browser and origin on HTTPS and ensure the Worker forwards `Set-Cookie` / `Cookie` headers (default behavior). |

The Cloudflare Worker intentionally does not cache the panel or API. Authentication and admin responses are always returned with `Cache-Control: no-store`.
