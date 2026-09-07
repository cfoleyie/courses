#!/usr/bin/env bash
# Keep Switch Time running in the background and bring it back after a reboot.
#
#   bash tools/install-service.sh
#
# Uses a systemd user service where one is available (including a Chromebook's
# Linux container on current ChromeOS), and falls back to a @reboot cron entry
# where it is not. Safe to re-run.

set -euo pipefail

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
die()  { printf '\n  %s✗ %s%s\n' "$RED" "$1" "$OFF" >&2; exit 1; }

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BIN="$ROOT/.venv/bin/switchtime"
ENV_FILE="$ROOT/.env.local"

[ -x "$BIN" ] || die "$BIN not found. Run tools/setup.sh first."
[ -f "$ROOT/config.toml" ] || die "config.toml not found. Run tools/setup.sh first."

step "Secrets file"
if [ -f "$ENV_FILE" ]; then
  ok ".env.local already exists, leaving it alone"
else
  cat > "$ENV_FILE" <<'ENVEOF'
# Read by the background service. Keep this file private; it is gitignored.
# Fill in the values, then restart the service.
NINTENDO_SESSION_TOKEN=
IXL_PASSWORD_OLIVER=
IXL_PASSWORD_ELEANOR=
IXL_PASSWORD_ALICE=
ENVEOF
  ok "created .env.local"
fi
chmod 600 "$ENV_FILE"
ok "permissions set to 600"

if ! grep -q '^NINTENDO_SESSION_TOKEN=.\+' "$ENV_FILE"; then
  warn "NINTENDO_SESSION_TOKEN is still blank in .env.local"
  warn "The service will run, but cannot touch the console until you fill it in."
fi

# A background service inherits nothing from your shell, so the secrets have to
# come from the file above rather than from `export`.
if systemctl --user show-environment >/dev/null 2>&1; then
  step "Installing a systemd user service"
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/switchtime.service" <<UNITEOF
[Unit]
Description=Switch Time — IXL lessons unlock Nintendo Switch play time
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$BIN serve
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF
  ok "wrote $UNIT_DIR/switchtime.service"

  # Without lingering, the service stops the moment you close the terminal.
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$USER" >/dev/null 2>&1 && ok "lingering enabled, so it survives logout" \
      || warn "could not enable lingering; the service may stop when you log out"
  fi

  systemctl --user daemon-reload
  systemctl --user enable --now switchtime.service
  sleep 2
  if systemctl --user is-active --quiet switchtime.service; then
    ok "service is running"
  else
    warn "service is not active. Logs: journalctl --user -u switchtime -n 50"
  fi

  cat <<EOF

${BOLD}Managing it:${OFF}
  systemctl --user status switchtime      # is it running
  systemctl --user restart switchtime     # after editing config.toml or .env.local
  systemctl --user stop switchtime
  journalctl --user -u switchtime -f      # follow the logs
EOF

else
  step "No systemd user session — falling back to cron"
  RUNNER="$ROOT/tools/run-service.sh"
  cat > "$RUNNER" <<RUNEOF
#!/usr/bin/env bash
# Started by cron at boot. Exits quietly if an instance is already up.
set -euo pipefail
cd "$ROOT"
if pgrep -f "$BIN serve" >/dev/null 2>&1; then exit 0; fi
set -a; . "$ENV_FILE"; set +a
mkdir -p "$ROOT/data"
exec "$BIN" serve >> "$ROOT/data/service.log" 2>&1
RUNEOF
  chmod +x "$RUNNER"
  ok "wrote $RUNNER"

  if command -v crontab >/dev/null 2>&1; then
    # Re-checking every 5 minutes also covers a container that was suspended.
    TMP="$(mktemp)"
    crontab -l 2>/dev/null | grep -v 'switchtime/tools/run-service.sh' > "$TMP" || true
    printf '@reboot %s\n*/5 * * * * %s\n' "$RUNNER" "$RUNNER" >> "$TMP"
    crontab "$TMP"
    rm -f "$TMP"
    ok "cron will start it at boot and re-check every 5 minutes"
    "$RUNNER" & sleep 2
    pgrep -f "$BIN serve" >/dev/null && ok "service is running" || warn "not running — see data/service.log"
  else
    warn "cron is not installed either. Start it by hand with: $RUNNER &"
  fi
fi

step "Where to reach it"
PORT="$(grep -E '^port' config.toml | head -1 | tr -dc '0-9' || echo 8777)"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "  On this machine : http://localhost:${PORT:-8777}"
[ -n "$IP" ] && echo "  On the network  : http://$IP:${PORT:-8777}"
echo
echo "  Installing it as an app on a phone needs HTTPS — see step 5 in README.md."
