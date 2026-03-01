#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_DIR="$HOME/.openclaw"

mkdir -p "$OPENCLAW_DIR"

echo "[restore] skills -> ~/.openclaw/skills"
if [ -d "$WS_DIR/skills" ]; then
  mkdir -p "$OPENCLAW_DIR/skills"
  rsync -av --delete "$WS_DIR/skills/" "$OPENCLAW_DIR/skills/"
fi

echo "[restore] extensions -> ~/.openclaw/extensions (optional)"
if [ -d "$WS_DIR/extensions" ] && [ "$(ls -A "$WS_DIR/extensions" 2>/dev/null || true)" != "" ]; then
  mkdir -p "$OPENCLAW_DIR/extensions"
  rsync -av --delete "$WS_DIR/extensions/" "$OPENCLAW_DIR/extensions/"
fi

echo "[restore] config template -> ~/.openclaw/openclaw.json"
if [ -f "$WS_DIR/config/openclaw.json" ]; then
  rsync -av "$WS_DIR/config/openclaw.json" "$OPENCLAW_DIR/openclaw.json"
  echo "NOTE: openclaw.json is a TEMPLATE; fill secrets via env vars or private/.env"
fi

echo "[restore] done."
