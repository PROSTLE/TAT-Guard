#!/usr/bin/env bash
# One command from a clean clone to the running demo on this machine (macOS or Linux).
#   bash scripts/run_demo.sh
# The first run takes about 10 minutes, nearly all of it Exasol's own download. Safe to run again.
# On macOS, run it from Terminal.app: an editor's built-in terminal may lack the Local Network permission the Exasol VM needs.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n== %s\n' "$1"; }
die() { printf '\nStopped: %s\n' "$1" >&2; exit 1; }

command -v uv >/dev/null || die "uv is needed for the Exasol MCP server. Install it: https://docs.astral.sh/uv/"
command -v exasol >/dev/null || die "Install Exasol Personal first: curl https://downloads.exasol.com/exasol-personal/installer.sh | sh"
PY=""
for c in python3.14 python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "Python 3.12 or later is needed."

say "Python environment"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt

say "Exasol"
STATUS="$(exasol status 2>/dev/null | sed -n 's/^Status: //p' || true)"
case "$STATUS" in
  database_ready) echo "Already running." ;;
  "") exasol install local ;;
  *) exasol start ;;
esac
SLC="$(exasol slc list 2>/dev/null | awk '/^python-/{print $NF}')"
[ "$SLC" = "yes" ] || exasol slc install PYTHON3 --auto-approve

say "Settings"
SECRETS="$HOME/.exasol/personal/deployments/default/secrets.json"
if [ ! -f .env ]; then
  [ -f "$SECRETS" ] || die "Cannot find the Exasol password. Copy .env.example to .env and fill it in."
  .venv/bin/python - "$SECRETS" > .env <<'PY'
import json, secrets, string, sys
admin = next(iter(json.load(open(sys.argv[1])).values()))
word = lambda: "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
print(f"""EXA_DSN=127.0.0.1/nocertcheck:8563
EXA_USER=sys
EXA_PASSWORD={admin}
TATGUARD_APP_USER=TATGUARD_APP
TATGUARD_APP_PASSWORD={word()}
TATGUARD_AGENT_USER=TATGUARD_AGENT
TATGUARD_AGENT_PASSWORD={word()}
TATGUARD_HOST_LABEL=exasol-personal-local""")
PY
  chmod 600 .env
  echo "Wrote .env. Add GEMINI_API_KEY there to switch on the AI analyst."
fi
set -a; . ./.env; set +a

say "Database users"
.venv/bin/python agent/setup_app_user.py
.venv/bin/python agent/setup_agent_user.py

say "Synthetic data"
[ -f data/1m/manifest.json ] || .venv/bin/python generator/generate.py --rows 1000000 --seed 42 --out data/1m
.venv/bin/python recon/pipeline.py load --data data/1m --reset-audit
.venv/bin/python verify/v1_load.py --data data/1m
.venv/bin/python recon/pipeline.py recon

say "Starting TAT Guard at http://127.0.0.1:8765"
exec .venv/bin/python ui/server.py
