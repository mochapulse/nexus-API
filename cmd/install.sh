#!/usr/bin/env bash

# Exit immediately on error, unset variable, or failed pipeline
set -euo pipefail

# Get the absolute path of the directory where this script resides (resolving symlinks)
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"

# Go up one directory to reach the ROOT PROJECT folder
PROJECT_ROOT="$( cd -P "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"

echo "📌 Script Location: $SCRIPT_DIR"
echo "📁 Project Root:    $PROJECT_ROOT"

sudo apt update
sudo apt install -y git curl wget build-essential cmake make python3-full

python3 -m venv venv
source venv/bin/activate
echo "🐍 Python Version: $(python3 --version)"
echo "📦 Virtual Environment: $SCRIPT_DIR/venv"
echo "📦 Activated Virtual Environment: $SCRIPT_DIR/venv"

pip install --upgrade pip
pip install -r "$REQUIREMENTS_FILE"
