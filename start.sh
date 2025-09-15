#!/bin/bash
# FastAPI Code Server Startup Script

# Set working directory
cd /opt/code-server

# Use the virtual environment Python directly
PYTHON_PATH="/root/venv/bin/python3"
PIP_PATH="/root/venv/bin/pip"

if [ -f "$PYTHON_PATH" ]; then
    echo "Using virtual environment: /root/venv"
    PYTHON_CMD="$PYTHON_PATH"
    PIP_CMD="$PIP_PATH"
else
    echo "Using system Python"
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
fi

# Set environment variables
export HOST=${HOST:-"0.0.0.0"}
export PORT=${PORT:-"8000"}
export DISPLAY=${DISPLAY:-":1"}

# Ensure VNC display is available for headed browsers
echo "Using DISPLAY: $DISPLAY"

# Install requirements if needed
if [ -f "requirements.txt" ]; then
    $PIP_CMD install -r requirements.txt
fi

# Start the FastAPI server
echo "Starting Code Server API on ${HOST}:${PORT}"
echo "Tailscale IP: 100.95.89.72"
echo "Access via: http://100.95.89.72:8000"
exec $PYTHON_CMD server.py