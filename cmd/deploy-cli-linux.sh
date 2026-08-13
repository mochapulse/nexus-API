#!/usr/bin/env bash

# Deploy the nexus-API CLI for workstation use.
#
# Creates ~/.nexus-API/workstation/ with:
#   .env   — production config (DEBUG=false, safe for real power commands)
#   venv/  — isolated Python virtualenv with pinned deps
#
# Adds a shell alias `nexus-API` that points at this workspace.
# Idempotent — safe to run multiple times.

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd -P "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"

WORKSTATION="$HOME/.nexus-API/workstation"
VENV_DIR="$WORKSTATION/venv"
REQUIREMENTS="$REPO_ROOT/requirements.txt"

# ── 1. Create workstation directory ──────────────────────────────────
echo "📁 Creating $WORKSTATION …"
mkdir -p "$WORKSTATION"

# ── 2. Copy .env.example → workstation/.env (force DEBUG=false) ─────
if [ ! -f "$WORKSTATION/.env" ]; then
  cp "$REPO_ROOT/api/.env.example" "$WORKSTATION/.env"
  sed -i 's/DEBUG=.*/DEBUG=false/' "$WORKSTATION/.env"
  echo "✅ Created workstation .env (DEBUG=false)"
else
  sed -i 's/DEBUG=.*/DEBUG=false/' "$WORKSTATION/.env"
  echo "✅ Workstation .env already exists (DEBUG=false enforced)"
fi

# ── 3. Create virtualenv + install deps ──────────────────────────────
if [ ! -f "$VENV_DIR/bin/python" ]; then
  echo "🐍 Creating virtualenv …"
  python3 -m venv "$VENV_DIR"
fi

echo "📦 Installing/updating dependencies …"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$REQUIREMENTS" -q

# ── 4. Detect shell rc file ─────────────────────────────────────────
detect_rc() {
  local base
  base="$(basename "${SHELL:-/bin/bash}")"
  case "$base" in
    zsh)  echo "$HOME/.zshrc" ;;
    bash) echo "$HOME/.bashrc" ;;
    *)    echo "$HOME/.profile" ;;
  esac
}
SHELL_RC="$(detect_rc)"

# ── 5. Add alias (idempotent) ──────────────────────────────────────
ALIAS_CMD="alias nexus-API='cd \"$REPO_ROOT\" && NEXUS_DOTENV_PATH=\"$WORKSTATION/.env\" \"$VENV_DIR/bin/python\" -m api.cli'"

if grep -qF "NEXUS_DOTENV_PATH" "$SHELL_RC" 2>/dev/null; then
  # Replace existing alias line
  sed -i "/NEXUS_DOTENV_PATH/c\\$ALIAS_CMD" "$SHELL_RC"
  echo "🔄 Updated alias in $SHELL_RC"
else
  echo "" >> "$SHELL_RC"
  echo "# nexus-API CLI (added by deploy-cli-linux.sh)" >> "$SHELL_RC"
  echo "$ALIAS_CMD" >> "$SHELL_RC"
  echo "➕ Added alias to $SHELL_RC"
fi

# ── 6. Verify ──────────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────"
echo "  Deploy complete"
echo "──────────────────────────────────────"
echo "  .env:     $WORKSTATION/.env  (DEBUG=false)"
echo "  venv:     $VENV_DIR"
echo "  alias:    nexus-API"
echo "  shell:    $SHELL_RC"
echo "──────────────────────────────────────"
echo ""
echo "Run:  source $SHELL_RC"
echo "Then: nexus-API --help"
