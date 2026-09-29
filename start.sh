#!/usr/bin/env bash
# Start the FX Hybrid Engine dashboard and open it in your browser. Runs on this computer only (127.0.0.1).
set -euo pipefail
cd "$(dirname "$0")/ui"
[ -f .next/BUILD_ID ] || exec ../install.sh
PORT=3055
export FXHE_UI_LOCAL_MODE=true
URL="http://127.0.0.1:$PORT/dashboard/overview"
up() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }
openurl() {
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
  else echo "Open $URL in your browser"; fi
}
if up; then echo "The dashboard is already running - opening $URL"; openurl; exit 0; fi
[ -n "${NO_BROWSER:-}" ] || ( for _ in $(seq 1 240); do if up; then openurl; exit 0; fi; sleep 0.5; done ) &
echo "Starting FX Hybrid Engine dashboard at $URL  (Ctrl+C to stop)"
exec npx next start -H 127.0.0.1 -p "$PORT"
