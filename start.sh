#!/bin/bash
#
# One-click launcher for Naukri Auto Applier & Profile Booster
# Usage: ./start.sh [boost|apply|all|agent|tracker|insights]
#

set -e

# Move into the script's directory
cd "$(dirname "$0")"

# Grant local user access to display server if running in X11/Xwayland
command -v xhost >/dev/null 2>&1 && xhost +si:localuser:"$USER" >/dev/null 2>&1 || true

VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"

# 1) Check for uv or python3
if command -v uv >/dev/null 2>&1; then
    RUNNER="uv"
elif command -v python3 >/dev/null 2>&1; then
    RUNNER="python"
else
    echo "Error: Neither uv nor python3 was found on this computer."
    exit 1
fi

# 2) Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    if [ "$RUNNER" = "uv" ]; then
        uv venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

# 3) Install dependencies if needed
if [ ! -f "$VENV_DIR/.deps_installed" ]; then
    echo "Installing required packages..."
    if [ "$RUNNER" = "uv" ]; then
        uv pip install --python "$VENV_PY" -r requirements.txt
    else
        "$VENV_PY" -m pip install --quiet --upgrade pip
        "$VENV_PY" -m pip install --quiet -r requirements.txt
    fi
    touch "$VENV_DIR/.deps_installed"
    echo "Dependencies installed successfully!"
fi

# 4) Run the bot
exec "$VENV_PY" main.py "$@"
