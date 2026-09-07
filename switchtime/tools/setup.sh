#!/usr/bin/env bash
# One-shot setup for Switch Time on a fresh Debian-ish machine (a Raspberry Pi,
# a home server, or a Chromebook's Linux container).
#
#   bash tools/setup.sh
#
# Safe to re-run: every step checks before it acts.

set -euo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
die()  { printf '\n  %s✗ %s%s\n' "$RED" "$1" "$OFF" >&2; exit 1; }

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

step "Checking prerequisites"
command -v python3 >/dev/null || die "python3 not found. On Debian/Ubuntu: sudo apt install python3 python3-venv"
PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 - <<'PYEOF' || die "Python 3.11 or newer is required (found $PY_VERSION)."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PYEOF
ok "python3 $PY_VERSION"

if ! python3 -c 'import venv' 2>/dev/null; then
  die "The venv module is missing. On Debian/Ubuntu: sudo apt install python3-venv"
fi

step "Creating the virtual environment"
if [ -d .venv ]; then
  ok ".venv already exists, reusing it"
else
  python3 -m venv .venv
  ok "created .venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
ok "pip up to date"

step "Installing Switch Time and its dependencies"
pip install --quiet -e ".[dev]"
ok "installed (this pulled in FastAPI, Playwright and the Nintendo client)"

step "Installing the headless browser IXL is read through"
if [ "${SWITCHTIME_SKIP_BROWSER:-}" = "1" ]; then
  warn "skipped (SWITCHTIME_SKIP_BROWSER=1)"
else
  # Needs system libraries; install-deps is a no-op if they are already present.
  if command -v sudo >/dev/null 2>&1; then
    playwright install-deps chromium >/dev/null 2>&1 || \
      warn "could not install system libraries automatically — if the browser fails later, run: sudo \$(which playwright) install-deps chromium"
  fi
  playwright install chromium >/dev/null
  ok "chromium ready"
fi

step "Setting up the config file"
if [ -f config.toml ]; then
  ok "config.toml already exists, leaving it alone"
else
  cp config.example.toml config.toml
  ok "created config.toml from the example"
fi

step "Running the test suite"
if pytest -q >/dev/null 2>&1; then
  ok "all tests pass"
else
  warn "tests did not all pass — the app may still run, but something is off"
fi

step "Checking what is wired up"
switchtime check-config || true

cat <<EOF

${BOLD}Setup finished.${OFF} ${DIM}Everything below happens in this directory:${OFF}
  $ROOT

${BOLD}What is left, in order:${OFF}

  ${BOLD}1.${OFF} Link the Nintendo account and find your console ids:
       source .venv/bin/activate
       switchtime nintendo-login       # prints a URL; paste the npf... link back
       export NINTENDO_SESSION_TOKEN='the token it printed'
       switchtime devices              # copy each id into config.toml

  ${BOLD}2.${OFF} Add each child's IXL password to your environment, matching the
     ixl_password_env names in config.toml:
       export IXL_PASSWORD_OLIVER='...'

  ${BOLD}3.${OFF} Change parent_pin in config.toml from 1234.

  ${BOLD}4.${OFF} Try one pass with dry_run still true, then start the server:
       switchtime sync oliver
       switchtime serve

  ${BOLD}5.${OFF} See README.md step 5 for putting it on a phone or Chromebook.
     That part needs HTTPS; a LAN address will not install.

EOF
