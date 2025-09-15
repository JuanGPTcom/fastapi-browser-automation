# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based browser automation and context management server that provides:
- **Persistent browser sessions** with Playwright for browser automation
- **Claude command execution** and context file management
- **Recording capabilities** for screenshots, videos, and interaction traces
- **Session-based workflows** for complex automation tasks

## Development Commands

### Starting the Server
```bash
# Start the FastAPI server (preferred method)
./start.sh

# Direct Python execution
python3 server.py

# With virtual environment
/root/venv/bin/python3 server.py
```

The server runs on `0.0.0.0:8000` by default and is accessible via Tailscale at `100.95.89.72:8000`.

### Dependencies
```bash
# Install dependencies
pip install -r requirements.txt

# Core dependencies: FastAPI, Uvicorn, Playwright, Python-multipart
```

### Environment Variables
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `DISPLAY`: X11 display for headed browsers (default: :1)

## Architecture

### Core Components

**FastAPI Application (`server.py`)**
- Main API server with comprehensive browser automation endpoints
- Built-in session management and recording capabilities
- Context management for Claude command execution

**SessionManager Class (`server.py:89-296`)**
- Manages persistent browser sessions with unique IDs
- Handles screenshot, video, and trace recording
- Provides session lifecycle management (create, use, close)
- Creates organized directory structure per session

**Recording System (`recordings/`)**
```
recordings/
├── sessions/           # Per-session organized recordings
│   └── session_{id}/
│       ├── metadata.json
│       ├── screenshots/
│       ├── videos/
│       └── traces/
├── screenshots/        # Global screenshots
├── videos/            # Global videos
└── temp/              # Temporary files
```

### Key API Endpoints

**Context Management:**
- `POST /api/context-in` - Write context data
- `GET /api/context` - Read context data
- `POST /api/execute` - Execute Claude commands

**Browser Automation:**
- `POST /api/browser` - One-shot browser automation
- `POST /api/sessions/create` - Create persistent session
- `POST /api/sessions/{id}/sequence` - Execute action sequences
- `POST /api/sessions/{id}/screenshot` - Take manual screenshots

**Session Management:**
- `GET /api/sessions` - List all sessions
- `GET /api/sessions/{id}/status` - Get session details
- `DELETE /api/sessions/{id}` - Close session
- `GET /api/sessions/{id}/export` - Export session as ZIP

### Browser Actions System

The server supports comprehensive browser automation through action sequences:
- **Navigation**: `goto`, `back`, `forward`, `reload`
- **Interaction**: `click`, `type`, `scroll`, `hover`
- **Waiting**: `wait`, `wait_for_selector`, `wait_for_load_state`
- **Recording**: `screenshot`, `start_trace`, `stop_trace`
- **Analysis**: `wait_for_screenshot_analysis` (integrates with Claude)

### Session Metadata Structure

Each session maintains detailed metadata in `metadata.json`:
- Session configuration (browser type, viewport, recording settings)
- Asset tracking (screenshots, videos, traces) with sequential naming
- Action history and timestamps
- Session status and lifecycle information

## Development Notes

### Session Directory Structure
Sessions are automatically organized with sequential asset naming:
- Screenshots: `001_action_description.png`
- Videos: `001_session_recording.webm`
- Traces: `001_interaction_trace.zip`

### Browser Configuration
- Supports Chromium, Firefox, and WebKit via Playwright
- Configurable viewport sizes and headless/headed modes
- Optional video recording with automatic file management
- VNC support for headed browsers with DISPLAY environment variable

### Context File Management
The server manages context files for Claude integration:
- `context.md` - Main context input/output
- Automatic context clearing and command execution tracking