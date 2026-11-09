#!/usr/bin/env bash
# Rozaneh one-command installer for Ubuntu/Debian VPS hosts with systemd.
# Example:
#   curl -fsSL https://raw.githubusercontent.com/ndnimanima/uityy/main/start.sh | sudo bash
# Overrides: ROZANEH_DIR, ROZANEH_REPO, ROZANEH_BRANCH, ROZANEH_PORT,
#            ADMIN_PASSWORD, DEFAULT_TZ, COOKIE_SECURE
set -euo pipefail

APP_DIR="${ROZANEH_DIR:-/opt/rozaneh}"
REPO="${ROZANEH_REPO:-https://github.com/ndnimanima/uityy.git}"
BRANCH="${ROZANEH_BRANCH:-main}"
PORT="${ROZANEH_PORT:-8080}"
SERVICE="rozaneh"

blue() { printf "\033[36m%s\033[0m\n" "$*"; }
ok()   { printf "\033[32m✓ %s\033[0m\n" "$*"; }
die()  { printf "\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this installer with sudo or as root."
command -v systemctl >/dev/null 2>&1 || die "systemd is required; use Docker on other hosts."
case "$APP_DIR" in /|/opt|/usr|/var) die "Unsafe ROZANEH_DIR: $APP_DIR" ;; esac

blue "▶ Installing prerequisites…"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates
else
  die "This helper targets Ubuntu/Debian. Docker is available for other Linux distributions."
fi

blue "▶ Preparing application source…"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
  if [ -z "$(git -C "$APP_DIR" status --porcelain)" ]; then
    git -C "$APP_DIR" reset --hard "origin/$BRANCH"
  else
    printf "Local changes detected; leaving the existing checkout untouched.\n"
  fi
else
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

blue "▶ Creating the Python environment…"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  if [ -n "${ADMIN_PASSWORD:-}" ]; then
    INITIAL_PASSWORD="$ADMIN_PASSWORD"
  else
    INITIAL_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  fi
  cat > "$APP_DIR/.env" <<EOF
ADMIN_PASSWORD=$INITIAL_PASSWORD
DATA_DIR=$APP_DIR/data
DEFAULT_TZ=${DEFAULT_TZ:-Asia/Tehran}
PORT=$PORT
COOKIE_SECURE=${COOKIE_SECURE:-0}
SCHEDULER_ENABLED=1
EOF
  chmod 600 "$APP_DIR/.env"
  ok "Initial admin password: $INITIAL_PASSWORD  (saved in $APP_DIR/.env)"
fi

id -u rozaneh >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin rozaneh
mkdir -p "$APP_DIR/data"
chown -R rozaneh:rozaneh "$APP_DIR/data"

blue "▶ Installing the systemd service…"
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=Rozaneh news and media automation panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \${PORT} --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=4
User=rozaneh
Group=rozaneh
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$APP_DIR/data

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE"
systemctl --no-pager --lines=6 status "$SERVICE" || true

ok "Rozaneh v1.06 is installed."
echo
echo "  Panel: http://$(hostname -I | awk '{print $1}'):$PORT"
echo "  First-run password: $APP_DIR/.env (ADMIN_PASSWORD)"
echo "  Logs: journalctl -u $SERVICE -f"
echo "  Put the panel behind HTTPS and set COOKIE_SECURE=1 before production use."
echo
