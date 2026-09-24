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

# Systemd unit the Minecraft watchdog is allowed to start/restart via
# polkit. Override to point at a different unit name if needed.
MC_UNIT="${MC_UNIT:-mc-server-create.service}"

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
    SERVICE_USER="${SUDO_USER:-$USER}"

    echo "Creating Polkit rule at ${RULE_FILE} for user '${SERVICE_USER}'..."

    # Note: EOF is unquoted so ${SERVICE_USER} expands inside the heredoc
    sudo tee "$RULE_FILE" > /dev/null << EOF
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.login1.power-off" ||
         action.id == "org.freedesktop.login1.power-off-multiple-sessions" ||
         action.id == "org.freedesktop.login1.power-off-ignore-inhibit" ||
         action.id == "org.freedesktop.login1.set-wall-message" ||
         action.id == "org.freedesktop.login1.suspend" ||
         action.id == "org.freedesktop.login1.suspend-multiple-sessions") &&
        (subject.user == "${SERVICE_USER}" || subject.isInGroup("users"))) {
        return polkit.Result.YES;
    }
});
EOF

    sudo chmod 644 "$RULE_FILE"

    MC_RULE_FILE="/etc/polkit-1/rules.d/20-nexus-mc-server.rules"

    echo "Creating Polkit rule at ${MC_RULE_FILE} for unit '${MC_UNIT}', user '${SERVICE_USER}'..."

    # Note: EOF is unquoted so ${MC_UNIT}/${SERVICE_USER} expand inside the heredoc
    sudo tee "$MC_RULE_FILE" > /dev/null << EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "${MC_UNIT}" &&
        (action.lookup("verb") == "start" || action.lookup("verb") == "restart") &&
        subject.user == "${SERVICE_USER}") {
        return polkit.Result.YES;
    }
});
EOF

    sudo chmod 644 "$MC_RULE_FILE"
    sudo systemctl restart polkit

    echo "Polkit rules deployed and polkit service restarted."
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
