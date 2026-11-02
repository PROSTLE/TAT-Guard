#!/usr/bin/env bash
# Put the demo on a public HTTPS link from this machine, behind an access code.
#   bash scripts/go_public.sh [access-code]
# Needs cloudflared (brew install cloudflared) and Exasol already running. Run it from Terminal.app.
#
# What this exposes: only the web app on port 8765. Exasol's own port stays on this machine. The server refuses every API
# call without the code, applies rate limits, and does not serve the routes that switch database or replace data.
# The link lasts while this script runs and this machine stays awake. A quick tunnel gets a new address each time it
# starts, so run it once and leave it, or use a named tunnel for a permanent address.
set -euo pipefail
cd "$(dirname "$0")/.."

die() { printf 'Stopped: %s\n' "$1" >&2; exit 1; }
command -v cloudflared >/dev/null || die "Install cloudflared first: brew install cloudflared"
nc -z 127.0.0.1 8563 2>/dev/null || die "Exasol is not running. Run: exasol start"
[ -f .env ] || die "No .env. Run scripts/run_demo.sh first."
lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1 && die "Port 8765 is in use. Stop the running server first."

CODE="${1:-$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(9))')}"
LOG="$(mktemp)"
trap 'kill "${SERVER:-}" "${TUNNEL:-}" 2>/dev/null || true; rm -f "$LOG"' EXIT

TATGUARD_ACCESS_CODE="$CODE" TATGUARD_PUBLIC_HOST=".trycloudflare.com" .venv/bin/python ui/server.py &
SERVER=$!
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765 >"$LOG" 2>&1 &
TUNNEL=$!

URL=""
for _ in $(seq 1 45); do
  URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { cat "$LOG"; die "The tunnel did not start."; }

printf '\nPublic link, ready to send:\n  %s/?code=%s\n\nAccess code on its own: %s\nPresenter reset: Proof page at http://127.0.0.1:8765\nPress Ctrl-C to take it offline.\n\n' "$URL" "$CODE" "$CODE"
if command -v caffeinate >/dev/null; then caffeinate -dims -w "$TUNNEL"; else wait "$TUNNEL"; fi
