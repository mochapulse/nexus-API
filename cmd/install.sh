#!/usr/bin/env bash

# Exit immediately on error, unset variable, or failed pipeline
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"

DEV_MODE=false
if [[ "${1:-}" == "-dev" ]]; then
    DEV_MODE=true
fi

PROJECT_ROOT="$( cd -P "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
VENV_DIR="$PROJECT_ROOT/venv"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"

echo "📌 Script Location: $SCRIPT_DIR"
echo "📁 Project Root:    $PROJECT_ROOT"
if $DEV_MODE; then
    echo "🔧 Dev mode — skipping polkit rule and systemd service."
fi

sudo apt update
sudo apt install -y git curl wget build-essential cmake make python3-full

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
echo "🐍 Python Version: $(python3 --version)"
echo "📦 Virtual Environment: $VENV_DIR"

pip install --upgrade pip
pip install -r "$REQUIREMENTS_FILE"

if ! $DEV_MODE; then
    RULE_FILE="/etc/polkit-1/rules.d/10-power-and-suspend.rules"

    echo "Creating Polkit rule at ${RULE_FILE}..."

    sudo tee "$RULE_FILE" > /dev/null << 'EOF'
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.login1.power-off" ||
         action.id == "org.freedesktop.login1.power-off-multiple-sessions" ||
         action.id == "org.freedesktop.login1.suspend" ||
         action.id == "org.freedesktop.login1.suspend-multiple-sessions") &&
        subject.isInGroup("users")) {
        return polkit.Result.YES;
    }
});
EOF

    sudo chmod 644 "$RULE_FILE"

    echo "Polkit rule deployed successfully."
fi

if ! $DEV_MODE; then
    SERVICE_USER="${SUDO_USER:-$USER}"
    SERVICE_SRC="$PROJECT_ROOT/daemon/nexus-api.service"
    SERVICE_DST="/etc/systemd/system/nexus-api.service"

    echo "Installing systemd service as user '${SERVICE_USER}'..."

    sed \
      -e "s|__USER__|${SERVICE_USER}|g" \
      -e "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
      "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null

    sudo chmod 644 "$SERVICE_DST"
    sudo systemctl daemon-reload
    sudo systemctl enable nexus-api

    echo "Systemd service installed and enabled."
    echo ""
    echo "Run the following to start the API now:"
    echo "  sudo systemctl start nexus-api"
    echo ""
    echo "Check status with:"
    echo "  systemctl status nexus-api"
    echo "View logs with:"
    echo "  journalctl -u nexus-api -f"
fi
