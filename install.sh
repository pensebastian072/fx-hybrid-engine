#!/usr/bin/env bash
# One-step install for the FX Hybrid Engine dashboard (macOS / Linux):  ./install.sh
# Installs the Next.js dashboard in ui/, builds it, then starts it. The Python engine is separate (see README).
set -euo pipefail
cd "$(dirname "$0")/ui"
command -v node >/dev/null 2>&1 || { echo "Node.js 20+ not found - install the LTS version from https://nodejs.org/"; exit 1; }
npm ci --no-audit --no-fund
npm run build
echo "Installed. Next time just run ./start.sh"
exec ../start.sh
