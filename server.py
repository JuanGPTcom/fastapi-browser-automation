#!/usr/bin/env python3
"""
FastAPI Server for Code Server
A simple FastAPI application with basic endpoints.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import os
import subprocess
import uuid
import asyncio
import time
import json
from datetime import datetime
from playwright.async_api import async_playwright
from typing import Dict
import weakref

# Set DISPLAY for headed browsers (VNC support)
os.environ['DISPLAY'] = ':1'

app = FastAPI(
    title="Code Server API",
    description="""
    ## Interactive Browser Automation & Context Management API
    
    A comprehensive FastAPI server providing:
    - **Persistent browser sessions** with screenshot analysis
    - **Claude command execution** and context file management  
    - **Browser automation** with recording capabilities
    - **Session-based workflows** for interactive automation
    
    ### Quick Start Examples:
    
    **1. Simple Context Management:**
    ```bash
    # Write context
    POST /api/context-in
    {"content": "Hello Claude"}
    
    # Execute Claude command
    POST /api/execute  
    {"command": "analyze the context"}
    
    # Read Claude output
    GET /api/context
    ```
    
    **2. Interactive Browser Session:**
    ```bash
    # Create session
    POST /api/sessions/create
    {"browser": "chromium", "headless": false}
    
    # Execute with screenshot checkpoints
    POST /api/sessions/{session_id}/sequence
    {
      "actions": [
        {"action": "goto", "url": "https://example.com", "screenshot_after": true},
        {"action": "wait_for_screenshot_analysis"},
        {"action": "click", "selector": ".login-btn", "screenshot_after": true}
      ]
    }
    ```
    
    **3. One-Shot Browser Automation:**
    ```bash
    POST /api/browser
    {
      "browser": "chromium",
      "record_video": true,
      "actions": [
        {"action": "goto", "url": "https://example.com"},
        {"action": "screenshot"}
      ]
    }
    ```
    """,
    version="2.0.0"
)

# Global session storage
active_sessions: Dict[str, Dict] = {}

class SessionManager:
    def __init__(self):
        self.sessions = {}
        self.recordings_base = "/opt/code-server/recordings"
    
    def _create_session_directory(self, session_id: str):
        """Create session-specific directory structure"""
        session_dir = f"{self.recordings_base}/sessions/session_{session_id}"
        os.makedirs(f"{session_dir}/screenshots", exist_ok=True)
        os.makedirs(f"{session_dir}/videos", exist_ok=True)
        os.makedirs(f"{session_dir}/traces", exist_ok=True)
        return session_dir
    
    def _save_session_metadata(self, session_id: str, metadata: dict):
        """Save session metadata to JSON file"""
        session_dir = f"{self.recordings_base}/sessions/session_{session_id}"
        metadata_path = f"{session_dir}/metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    async def create_session(self, session_id: str, browser_type: str = "chromium", headless: bool = True, viewport_width: int = 1280, viewport_height: int = 720, record_video: bool = False):
        async def _create():
            playwright = await async_playwright().__aenter__()
            browser_launcher = getattr(playwright, browser_type)
            browser = await browser_launcher.launch(headless=headless)
            
            # Configure context with optional video recording
            context_options = {"viewport": {"width": viewport_width, "height": viewport_height}}
            
            if record_video:
                session_dir = f"{self.recordings_base}/sessions/session_{session_id}"
                video_dir = f"{session_dir}/videos"
                context_options.update({
                    "record_video_dir": video_dir,
                    "record_video_size": {"width": viewport_width, "height": viewport_height}
                })
            
            context = await browser.new_context(**context_options)
            page = await context.new_page()
            
            return {
                "playwright": playwright,
                "browser": browser, 
                "context": context,
                "page": page,
                "screenshots": [],
                "videos": [],
                "traces": [],
                "created_at": time.time(),
                "action_count": 0,
                "last_activity": time.time(),
                "recording_video": record_video
            }
        
        # Create session directory structure
        session_dir = self._create_session_directory(session_id)
        
        # Create session data
        session_data = await _create()
        
        # Create initial metadata
        metadata = {
            "session_id": session_id,
            "created_at": datetime.fromtimestamp(session_data["created_at"]).isoformat(),
            "browser_type": browser_type,
            "headless": headless,
            "viewport": {"width": viewport_width, "height": viewport_height},
            "record_video": record_video,
            "status": "active",
            "total_actions": 0,
            "screenshots": [],
            "videos": [],
            "traces": [],
            "last_activity": datetime.fromtimestamp(session_data["last_activity"]).isoformat(),
            "session_dir": session_dir
        }
        
        session_data["metadata"] = metadata
        self._save_session_metadata(session_id, metadata)
        
        self.sessions[session_id] = session_data
        return session_data
    
    async def get_session(self, session_id: str):
        return self.sessions.get(session_id)
    
    def _get_next_sequence_number(self, session_id: str, asset_type: str):
        """Get next sequential number for asset naming"""
        session = self.sessions.get(session_id)
        if not session:
            return 1
        
        assets = session["metadata"][asset_type]
        return len(assets) + 1
    
    def add_screenshot(self, session_id: str, action: str, description: str = "", url: str = ""):
        """Add screenshot to session with sequential naming"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        seq_num = self._get_next_sequence_number(session_id, "screenshots")
        filename = f"{seq_num:03d}_{action}_{description}.png".replace(" ", "_")
        session_dir = session["metadata"]["session_dir"]
        filepath = f"{session_dir}/screenshots/{filename}"
        
        # Update session metadata
        screenshot_entry = {
            "filename": filename,
            "filepath": filepath,
            "action": action,
            "description": description,
            "url": url,
            "sequence": seq_num,
            "timestamp": datetime.now().isoformat()
        }
        
        session["screenshots"].append(filepath)
        session["metadata"]["screenshots"].append(screenshot_entry)
        session["metadata"]["total_actions"] += 1
        session["metadata"]["last_activity"] = datetime.now().isoformat()
        session["last_activity"] = time.time()
        
        self._save_session_metadata(session_id, session["metadata"])
        return filepath
    
    def add_video(self, session_id: str, description: str = "session_recording"):
        """Add video to session with sequential naming"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        seq_num = self._get_next_sequence_number(session_id, "videos")
        filename = f"{seq_num:03d}_{description}.webm".replace(" ", "_")
        session_dir = session["metadata"]["session_dir"]
        filepath = f"{session_dir}/videos/{filename}"
        
        video_entry = {
            "filename": filename,
            "filepath": filepath,
            "description": description,
            "sequence": seq_num,
            "timestamp": datetime.now().isoformat()
        }
        
        session["videos"].append(filepath)
        session["metadata"]["videos"].append(video_entry)
        session["metadata"]["last_activity"] = datetime.now().isoformat()
        
        self._save_session_metadata(session_id, session["metadata"])
        return filepath
    
    def add_trace(self, session_id: str, description: str = "interaction_trace"):
        """Add trace to session with sequential naming"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        seq_num = self._get_next_sequence_number(session_id, "traces")
        filename = f"{seq_num:03d}_{description}.zip".replace(" ", "_")
        session_dir = session["metadata"]["session_dir"]
        filepath = f"{session_dir}/traces/{filename}"
        
        trace_entry = {
            "filename": filename,
            "filepath": filepath,
            "description": description,
            "sequence": seq_num,
            "timestamp": datetime.now().isoformat()
        }
        
        session["traces"].append(filepath)
        session["metadata"]["traces"].append(trace_entry)
        session["metadata"]["last_activity"] = datetime.now().isoformat()
        
        self._save_session_metadata(session_id, session["metadata"])
        return filepath
    
    async def close_session(self, session_id: str):
        if session_id in self.sessions:
            session = self.sessions[session_id]
            
            # If video recording was enabled, add the video file to session metadata
            if session["metadata"].get("record_video", False):
                # Playwright automatically saves videos when the context closes
                # Video is saved to the record_video_dir path specified during context creation
                video_path = session["metadata"]["session_dir"] + "/videos/"
                if os.path.exists(video_path):
                    # Find the generated video file (usually named with a UUID)
                    video_files = [f for f in os.listdir(video_path) if f.endswith('.webm')]
                    if video_files:
                        # Rename to our sequential naming convention
                        original_video = os.path.join(video_path, video_files[0])
                        new_video_path = self.add_video(session_id, "session_recording")
                        if new_video_path and os.path.exists(original_video):
                            os.rename(original_video, new_video_path)
            
            # Update metadata status to completed
            session["metadata"]["status"] = "completed"
            session["metadata"]["last_activity"] = datetime.now().isoformat()
            self._save_session_metadata(session_id, session["metadata"])
            
            await session["context"].close()
            await session["browser"].close()
            await session["playwright"].__aexit__(None, None, None)
            del self.sessions[session_id]

session_manager = SessionManager()

class ContextInput(BaseModel):
    content: str

class CommandInput(BaseModel):
    command: Optional[str] = None
    term: Optional[str] = None

class BrowserAction(BaseModel):
    action: str  # "goto", "click", "type", "screenshot", "wait"
    selector: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None
    timeout: Optional[int] = 5000

class BrowserSessionInput(BaseModel):
    browser: Optional[str] = "chromium"  # chromium, firefox, webkit
    headless: Optional[bool] = True
    record_video: Optional[bool] = False
    enable_tracing: Optional[bool] = False
    actions: List[BrowserAction]
    viewport_width: Optional[int] = 1280
    viewport_height: Optional[int] = 720

class SessionCreateInput(BaseModel):
    browser: Optional[str] = "chromium"
    headless: Optional[bool] = True
    viewport_width: Optional[int] = 1280
    viewport_height: Optional[int] = 720
    timeout: Optional[int] = 3600
    record_video: Optional[bool] = False

class SequenceAction(BaseModel):
    action: str
    url: Optional[str] = None
    selector: Optional[str] = None
    text: Optional[str] = None
    timeout: Optional[int] = 5000
    screenshot_after: Optional[bool] = False
    wait_for_analysis: Optional[bool] = False

class SequenceInput(BaseModel):
    actions: List[SequenceAction]

class NaturalLanguageInput(BaseModel):
    instruction: str
    include_screenshot: Optional[bool] = True

@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint returning HTML status page"""
    return """
    <html>
        <head><title>Code Server API</title></head>
        <body>
            <h1>Code Server API</h1>
            <p>Server is running successfully!</p>
            <p>Time: {}</p>
            <p><a href="/docs">API Documentation</a></p>
        </body>
    </html>
    """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

@app.get("/api/info")
async def get_info():
    """Get server information"""
    return {
        "server": "Code Server API",
        "version": "1.0.0",
        "python_version": os.sys.version,
        "uptime": datetime.now().isoformat()
    }

@app.get("/api/context")
async def get_context():
    """Read contents of context-out.txt from root directory"""
    context_file_path = "/root/context-out.txt"
    
    try:
        with open(context_file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        return {
            "status": "success",
            "file_path": context_file_path,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="context-out.txt file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@app.post("/api/context-in")
async def write_context_in(input_data: ContextInput):
    """Write content to context-in.txt in root directory"""
    context_file_path = "/root/context-in.txt"
    
    try:
        with open(context_file_path, 'w', encoding='utf-8') as file:
            file.write(input_data.content)
        
        return {
            "status": "success",
            "message": "Content written to context-in.txt",
            "file_path": context_file_path,
            "content_length": len(input_data.content),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")

@app.post("/api/execute")
async def execute_command(command_data: CommandInput):
    """Execute either claude -p [command] or direct terminal command"""
    try:
        # Validate that only one key is provided
        provided_keys = []
        if command_data.command is not None:
            provided_keys.append("command")
        if command_data.term is not None:
            provided_keys.append("term")
        
        if len(provided_keys) == 0:
            raise HTTPException(status_code=400, detail="Format error: Either 'command' or 'term' key must be provided")
        elif len(provided_keys) > 1:
            raise HTTPException(status_code=400, detail="Format error: Only one key allowed at a time. Use either 'command' or 'term', not both")
        
        if command_data.command is not None:
            # Execute claude command
            claude_command = ["claude", "-p", command_data.command]
            result = subprocess.run(
                claude_command,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd="/root"  # Execute from root directory
            )
            
            return {
                "status": "success",
                "command": f"claude -p {command_data.command}",
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timestamp": datetime.now().isoformat()
            }
        
        elif command_data.term is not None:
            # Execute direct terminal command
            terminal_command = command_data.term.split()
            result = subprocess.run(
                terminal_command,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd="/root",  # Execute from root directory
                shell=False  # Use shell=False for security
            )
            
            return {
                "status": "success",
                "command": command_data.term,
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timestamp": datetime.now().isoformat()
            }
            
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Command execution timed out (30s)")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Command not found: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing command: {str(e)}")

@app.post("/api/browser")
async def browser_automation(session_data: BrowserSessionInput):
    """Execute browser automation with optional recording"""
    session_id = str(uuid.uuid4())[:8]
    recordings_dir = "/opt/code-server/recordings"
    
    # Prepare recording paths
    video_path = None
    trace_path = None
    screenshots = []
    
    if session_data.record_video:
        video_path = f"{recordings_dir}/videos"
    
    if session_data.enable_tracing:
        trace_path = f"{recordings_dir}/traces/trace_{session_id}.zip"
    
    try:
        async with async_playwright() as p:
            # Launch browser
            browser_type = getattr(p, session_data.browser)
            
            context_options = {
                "viewport": {
                    "width": session_data.viewport_width,
                    "height": session_data.viewport_height
                }
            }
            
            if session_data.record_video:
                context_options["record_video_dir"] = video_path
                context_options["record_video_size"] = {
                    "width": session_data.viewport_width,
                    "height": session_data.viewport_height
                }
            
            browser = await browser_type.launch(headless=session_data.headless)
            context = await browser.new_context(**context_options)
            
            # Start tracing if enabled
            if session_data.enable_tracing:
                await context.tracing.start(screenshots=True, snapshots=True)
            
            page = await context.new_page()
            
            # Execute actions
            action_results = []
            for i, action in enumerate(session_data.actions):
                try:
                    if action.action == "goto":
                        await page.goto(action.url, timeout=action.timeout)
                        action_results.append({"action": "goto", "url": action.url, "status": "success"})
                    
                    elif action.action == "click":
                        await page.click(action.selector, timeout=action.timeout)
                        action_results.append({"action": "click", "selector": action.selector, "status": "success"})
                    
                    elif action.action == "type":
                        await page.fill(action.selector, action.text)
                        action_results.append({"action": "type", "selector": action.selector, "status": "success"})
                    
                    elif action.action == "screenshot":
                        screenshot_path = f"{recordings_dir}/screenshots/screenshot_{session_id}_{i}.png"
                        await page.screenshot(path=screenshot_path)
                        screenshots.append(screenshot_path)
                        action_results.append({"action": "screenshot", "path": screenshot_path, "status": "success"})
                    
                    elif action.action == "wait":
                        await page.wait_for_timeout(action.timeout)
                        action_results.append({"action": "wait", "timeout": action.timeout, "status": "success"})
                    
                    else:
                        action_results.append({"action": action.action, "status": "error", "message": "Unknown action"})
                
                except Exception as e:
                    action_results.append({"action": action.action, "status": "error", "message": str(e)})
            
            # Stop tracing if enabled
            if session_data.enable_tracing:
                await context.tracing.stop(path=trace_path)
            
            # Get video path if recorded
            video_file = None
            if session_data.record_video:
                await context.close()
                # Video file will be in the video directory
                import glob
                video_files = glob.glob(f"{video_path}/*.webm")
                if video_files:
                    # Rename to session-specific name
                    video_file = f"{recordings_dir}/videos/session_{session_id}.webm"
                    os.rename(video_files[0], video_file)
            
            await browser.close()
            
            return {
                "status": "success",
                "session_id": session_id,
                "actions_executed": len(action_results),
                "action_results": action_results,
                "recordings": {
                    "video": video_file if video_file else None,
                    "trace": trace_path if session_data.enable_tracing else None,
                    "screenshots": screenshots
                },
                "timestamp": datetime.now().isoformat()
            }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Browser automation error: {str(e)}")

@app.get("/api/recordings")
async def list_recordings():
    """List all available recordings"""
    recordings_dir = "/opt/code-server/recordings"
    
    try:
        import glob
        
        videos = glob.glob(f"{recordings_dir}/videos/*.webm")
        traces = glob.glob(f"{recordings_dir}/traces/*.zip")
        screenshots = glob.glob(f"{recordings_dir}/screenshots/*.png")
        
        return {
            "status": "success",
            "recordings": {
                "videos": [os.path.basename(v) for v in videos],
                "traces": [os.path.basename(t) for t in traces],
                "screenshots": [os.path.basename(s) for s in screenshots]
            },
            "total_files": len(videos) + len(traces) + len(screenshots),
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing recordings: {str(e)}")

@app.get("/api/recordings/{recording_type}/{filename}")
async def download_recording(recording_type: str, filename: str):
    """Download a specific recording file"""
    if recording_type not in ["videos", "traces", "screenshots"]:
        raise HTTPException(status_code=400, detail="Invalid recording type. Use: videos, traces, or screenshots")
    
    file_path = f"/opt/code-server/recordings/{recording_type}/{filename}"
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Recording file not found")
    
    return FileResponse(file_path, filename=filename)

@app.post("/api/sessions/create")
async def create_session(session_input: SessionCreateInput):
    """
    Create persistent browser session for interactive automation
    
    **Example:**
    ```bash
    curl -X POST http://100.95.89.72:8000/api/sessions/create \\
      -H "Content-Type: application/json" \\
      -d '{"browser": "chromium", "headless": false}'
    ```
    
    **Response:**
    ```json
    {
      "status": "success",
      "session_id": "abc12345",
      "timeout": 3600
    }
    ```
    """
    session_id = str(uuid.uuid4())[:8]
    
    try:
        await session_manager.create_session(
            session_id, 
            session_input.browser, 
            session_input.headless,
            session_input.viewport_width,
            session_input.viewport_height,
            session_input.record_video
        )
        
        return {
            "status": "success",
            "session_id": session_id,
            "timeout": session_input.timeout,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

@app.get("/api/sessions")
async def list_active_sessions():
    """
    List all active browser sessions
    
    **Example:**
    ```bash
    curl http://100.95.89.72:8000/api/sessions
    ```
    
    **Response:**
    ```json
    {
      "status": "success",
      "active_sessions": [
        {
          "session_id": "abc12345",
          "created_at": "2025-09-10T23:15:33.356075",
          "browser_type": "chromium",
          "headless": true,
          "record_video": true,
          "total_actions": 5,
          "last_activity": "2025-09-10T23:20:15.123456"
        }
      ],
      "total_sessions": 1,
      "timestamp": "2025-09-10T23:25:00.000000"
    }
    ```
    """
    active_sessions = []
    
    for session_id, session_data in session_manager.sessions.items():
        metadata = session_data["metadata"]
        active_sessions.append({
            "session_id": session_id,
            "created_at": metadata["created_at"],
            "browser_type": metadata["browser_type"],
            "headless": metadata["headless"],
            "record_video": metadata.get("record_video", False),
            "status": metadata["status"],
            "total_actions": metadata["total_actions"],
            "last_activity": metadata["last_activity"],
            "viewport": metadata["viewport"]
        })
    
    return {
        "status": "success",
        "active_sessions": active_sessions,
        "total_sessions": len(active_sessions),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Check session status"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "status": "active",
        "session_id": session_id,
        "created_at": session["created_at"],
        "screenshots_count": len(session["screenshots"]),
        "timestamp": datetime.now().isoformat()
    }

@app.delete("/api/sessions/{session_id}")
async def close_session(session_id: str):
    """Close browser session"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await session_manager.close_session(session_id)
    return {
        "status": "success",
        "message": "Session closed",
        "session_id": session_id,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/sessions/{session_id}/sequence")
async def execute_sequence(session_id: str, sequence_input: SequenceInput):
    """
    Execute action sequence with screenshot checkpoints and analysis pausing
    
    **Key Features:**
    - Executes actions sequentially on persistent browser session
    - Takes screenshots after actions when `screenshot_after: true`
    - Pauses execution on `wait_for_screenshot_analysis` for human review
    - Maintains session state between API calls
    
    **Example:**
    ```bash
    curl -X POST http://100.95.89.72:8000/api/sessions/abc12345/sequence \\
      -H "Content-Type: application/json" \\
      -d '{
        "actions": [
          {"action": "goto", "url": "https://httpbin.org/forms/post", "screenshot_after": true},
          {"action": "wait_for_screenshot_analysis", "timeout": 30000},
          {"action": "click", "selector": "input[name=custname]", "screenshot_after": false},
          {"action": "type", "selector": "input[name=custname]", "text": "John Doe"}
        ]
      }'
    ```
    
    **When hitting `wait_for_screenshot_analysis`, returns:**
    ```json
    {
      "status": "paused_for_analysis",
      "screenshot_for_analysis": "/path/to/screenshot.png",
      "message": "Review screenshot and call /api/sessions/abc12345/continue"
    }
    ```
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    page = session["page"]
    recordings_dir = "/opt/code-server/recordings"
    action_results = []
    screenshots = []
    
    try:
        for i, action in enumerate(sequence_input.actions):
            result = {"action": action.action, "step": i}
            
            if action.action == "goto":
                await page.goto(action.url, timeout=action.timeout)
                result["url"] = action.url
                result["status"] = "success"
            
            elif action.action == "click":
                await page.click(action.selector, timeout=action.timeout)
                result["selector"] = action.selector
                result["status"] = "success"
            
            elif action.action == "type":
                await page.fill(action.selector, action.text)
                result["selector"] = action.selector
                result["text"] = action.text
                result["status"] = "success"
            
            elif action.action == "wait":
                await page.wait_for_timeout(action.timeout)
                result["timeout"] = action.timeout
                result["status"] = "success"
            
            elif action.action == "wait_for_screenshot_analysis":
                # This pauses execution and returns current state for analysis
                screenshot_path = f"{recordings_dir}/screenshots/session_{session_id}_analysis_{i}.png"
                await page.screenshot(path=screenshot_path)
                screenshots.append(screenshot_path)
                session["screenshots"].append(screenshot_path)
                
                result["status"] = "waiting_for_analysis"
                result["screenshot_path"] = screenshot_path
                result["message"] = "Execution paused - analyze screenshot and continue with next API call"
                action_results.append(result)
                
                return {
                    "status": "paused_for_analysis",
                    "session_id": session_id,
                    "current_step": i,
                    "screenshot_for_analysis": screenshot_path,
                    "next_actions": sequence_input.actions[i+1:],
                    "completed_actions": action_results,
                    "message": "Review screenshot and call /api/sessions/{session_id}/continue to proceed"
                }
            
            else:
                result["status"] = "error"
                result["message"] = f"Unknown action: {action.action}"
            
            # Take screenshot after action if requested
            if action.screenshot_after:
                screenshot_path = f"{recordings_dir}/screenshots/session_{session_id}_step_{i}.png"
                await page.screenshot(path=screenshot_path)
                screenshots.append(screenshot_path)
                session["screenshots"].append(screenshot_path)
                result["screenshot_path"] = screenshot_path
            
            action_results.append(result)
        
        return {
            "status": "completed",
            "session_id": session_id,
            "actions_executed": len(action_results),
            "action_results": action_results,
            "screenshots": screenshots,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        # Take error screenshot
        error_screenshot = f"{recordings_dir}/screenshots/session_{session_id}_error.png"
        await page.screenshot(path=error_screenshot)
        
        return {
            "status": "error",
            "session_id": session_id,
            "error": str(e),
            "error_screenshot": error_screenshot,
            "completed_actions": action_results,
            "timestamp": datetime.now().isoformat()
        }

@app.post("/api/sessions/{session_id}/screenshot")
async def take_screenshot(session_id: str, include_base64: bool = False):
    """
    Take screenshot of current page state in persistent session
    
    **Parameters:**
    - `include_base64`: Set to `true` to include base64-encoded image data in response
    
    **Example:**
    ```bash
    # Get screenshot with base64 data
    curl -X POST "http://100.95.89.72:8000/api/sessions/abc12345/screenshot?include_base64=true"
    
    # Get screenshot path only
    curl -X POST "http://100.95.89.72:8000/api/sessions/abc12345/screenshot"
    ```
    
    **Response with base64:**
    ```json
    {
      "status": "success",
      "screenshot_path": "/opt/code-server/recordings/screenshots/session_abc12345_1694123456.png",
      "screenshot_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
      "screenshot_size": 25432
    }
    ```
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    page = session["page"]
    
    # Use SessionManager to create properly named screenshot
    screenshot_path = session_manager.add_screenshot(session_id, "manual", "screenshot")
    
    await page.screenshot(path=screenshot_path)
    
    response = {
        "status": "success",
        "session_id": session_id,
        "screenshot_path": screenshot_path,
        "timestamp": datetime.now().isoformat()
    }
    
    if include_base64:
        import base64
        with open(screenshot_path, "rb") as f:
            screenshot_bytes = f.read()
            response["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode('utf-8')
            response["screenshot_size"] = len(screenshot_bytes)
    
    return response

@app.post("/api/sessions/{session_id}/natural")
async def execute_natural_language(session_id: str, nl_input: NaturalLanguageInput):
    """
    Execute browser actions from natural language instructions
    
    **Example:**
    ```bash
    curl -X POST http://100.95.89.72:8000/api/sessions/abc12345/natural \\
      -H "Content-Type: application/json" \\
      -d '{
        "instruction": "Go to google.com and search for playwright automation",
        "include_screenshot": true
      }'
    ```
    
    **Response:**
    ```json
    {
      "status": "completed",
      "instruction": "Go to google.com and search for playwright automation",
      "generated_actions": [...],
      "action_results": [...],
      "screenshot_path": "..."
    }
    ```
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        # Create prompt template for Claude
        prompt_template = f"""Convert this natural language browser instruction into a JSON array of Playwright actions.

USER INSTRUCTION: "{nl_input.instruction}"

Return ONLY a valid JSON array with actions. Available actions:
- {{"action": "goto", "url": "https://example.com"}}
- {{"action": "click", "selector": "button.submit"}}  
- {{"action": "type", "selector": "input[name='q']", "text": "search term"}}
- {{"action": "wait", "timeout": 3000}}
- {{"action": "screenshot"}}

Example output:
[
  {{"action": "goto", "url": "https://google.com"}},
  {{"action": "click", "selector": "input[name='q']"}},
  {{"action": "type", "selector": "input[name='q']", "text": "playwright automation"}},
  {{"action": "click", "selector": "input[value='Google Search']"}}
]

JSON array:"""

        # Execute Claude command to convert natural language
        claude_command = ["claude", "-p", prompt_template]
        result = subprocess.run(
            claude_command,
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/root"
        )
        
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Claude command failed: {result.stderr}")
        
        # Parse Claude's JSON response
        import json
        import re
        try:
            # Extract JSON from markdown code blocks if present
            claude_output = result.stdout.strip()
            
            # Look for JSON in ```json blocks
            json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', claude_output, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)
            else:
                # Try to find JSON array directly
                json_match = re.search(r'(\[.*?\])', claude_output, re.DOTALL)
                if json_match:
                    json_text = json_match.group(1)
                else:
                    json_text = claude_output
            
            generated_actions = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse Claude response as JSON: {str(e)}\nResponse: {result.stdout}")
        
        # Convert to SequenceAction objects and execute
        page = session["page"]
        action_results = []
        screenshot_path = None
        
        for i, action_data in enumerate(generated_actions):
            result_item = {"action": action_data.get("action"), "step": i}
            
            if action_data["action"] == "goto":
                await page.goto(action_data["url"], timeout=action_data.get("timeout", 30000))
                result_item["url"] = action_data["url"]
                result_item["status"] = "success"
                
                # Auto-screenshot after navigation
                screenshot_path = session_manager.add_screenshot(session_id, "goto", f"navigate_to_{action_data['url'].replace('https://', '').replace('http://', '').replace('/', '_')}", action_data["url"])
                await page.screenshot(path=screenshot_path)
                result_item["screenshot_path"] = screenshot_path
            
            elif action_data["action"] == "click":
                await page.click(action_data["selector"], timeout=action_data.get("timeout", 5000))
                result_item["selector"] = action_data["selector"]
                result_item["status"] = "success"
                
                # Auto-screenshot after click
                screenshot_path = session_manager.add_screenshot(session_id, "click", f"clicked_{action_data['selector'].replace(' ', '_')}")
                await page.screenshot(path=screenshot_path)
                result_item["screenshot_path"] = screenshot_path
            
            elif action_data["action"] == "type":
                await page.fill(action_data["selector"], action_data["text"])
                result_item["selector"] = action_data["selector"]
                result_item["text"] = action_data["text"]
                result_item["status"] = "success"
                
                # Auto-screenshot after typing
                screenshot_path = session_manager.add_screenshot(session_id, "type", f"typed_in_{action_data['selector'].replace(' ', '_')}")
                await page.screenshot(path=screenshot_path)
                result_item["screenshot_path"] = screenshot_path
            
            elif action_data["action"] == "wait":
                await page.wait_for_timeout(action_data.get("timeout", 3000))
                result_item["timeout"] = action_data.get("timeout", 3000)
                result_item["status"] = "success"
                
            elif action_data["action"] == "screenshot":
                screenshot_path = session_manager.add_screenshot(session_id, "screenshot", "manual_screenshot")
                await page.screenshot(path=screenshot_path)
                result_item["screenshot_path"] = screenshot_path
                result_item["status"] = "success"
            
            else:
                result_item["status"] = "error"
                result_item["message"] = f"Unknown action: {action_data['action']}"
            
            action_results.append(result_item)
        
        # Take final screenshot if requested and no screenshot was taken
        if nl_input.include_screenshot and not screenshot_path:
            screenshot_path = session_manager.add_screenshot(session_id, "final", "completion_screenshot")
            await page.screenshot(path=screenshot_path)
        
        return {
            "status": "completed",
            "session_id": session_id,
            "instruction": nl_input.instruction,
            "generated_actions": generated_actions,
            "actions_executed": len(action_results),
            "action_results": action_results,
            "screenshot_path": screenshot_path,
            "timestamp": datetime.now().isoformat()
        }
    
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Claude command timed out")
    except Exception as e:
        # Take error screenshot
        page = session["page"]
        error_screenshot = session_manager.add_screenshot(session_id, "error", f"nl_error_{str(e)[:20].replace(' ', '_')}")
        await page.screenshot(path=error_screenshot)
        
        return {
            "status": "error", 
            "session_id": session_id,
            "instruction": nl_input.instruction,
            "error": str(e),
            "error_screenshot": error_screenshot,
            "timestamp": datetime.now().isoformat()
        }

@app.get("/api/sessions/{session_id}/assets")
async def get_session_assets(session_id: str):
    """
    Get all assets (screenshots, videos, traces) for a session
    
    **Example:**
    ```bash
    curl http://100.95.89.72:8000/api/sessions/abc12345/assets
    ```
    
    **Response:**
    ```json
    {
      "session_id": "abc12345",
      "status": "active",
      "total_screenshots": 5,
      "total_videos": 1,
      "total_traces": 1,
      "assets": {
        "screenshots": [...],
        "videos": [...],
        "traces": [...]
      }
    }
    ```
    """
    session = await session_manager.get_session(session_id)
    if not session:
        # Try to load from disk if session not in memory
        session_dir = f"/opt/code-server/recordings/sessions/session_{session_id}"
        metadata_path = f"{session_dir}/metadata.json"
        
        if not os.path.exists(metadata_path):
            raise HTTPException(status_code=404, detail="Session not found")
        
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
    else:
        metadata = session["metadata"]
    
    return {
        "session_id": session_id,
        "status": metadata["status"],
        "created_at": metadata["created_at"],
        "last_activity": metadata["last_activity"],
        "total_actions": metadata["total_actions"],
        "total_screenshots": len(metadata["screenshots"]),
        "total_videos": len(metadata["videos"]),
        "total_traces": len(metadata["traces"]),
        "assets": {
            "screenshots": metadata["screenshots"],
            "videos": metadata["videos"],
            "traces": metadata["traces"]
        },
        "session_dir": metadata["session_dir"],
        "timestamp": datetime.now().isoformat()
    }

@app.delete("/api/sessions/{session_id}/cleanup")
async def cleanup_session(session_id: str):
    """
    Clean up all assets for a specific session
    
    **Example:**
    ```bash
    curl -X DELETE http://100.95.89.72:8000/api/sessions/abc12345/cleanup
    ```
    """
    import shutil
    
    # Close active session if running
    if session_id in session_manager.sessions:
        await session_manager.close_session(session_id)
    
    # Remove session directory
    session_dir = f"/opt/code-server/recordings/sessions/session_{session_id}"
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir)
        return {
            "status": "success",
            "message": f"Session {session_id} cleaned up",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    else:
        raise HTTPException(status_code=404, detail="Session directory not found")

@app.post("/api/sessions/cleanup-old")
async def cleanup_old_sessions(max_age_hours: int = 24):
    """
    Clean up sessions older than specified hours
    
    **Example:**
    ```bash
    curl -X POST "http://100.95.89.72:8000/api/sessions/cleanup-old?max_age_hours=24"
    ```
    """
    import shutil
    import glob
    
    sessions_dir = "/opt/code-server/recordings/sessions"
    if not os.path.exists(sessions_dir):
        return {"status": "success", "cleaned_sessions": [], "message": "No sessions directory found"}
    
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_sessions = []
    
    for session_path in glob.glob(f"{sessions_dir}/session_*"):
        metadata_path = f"{session_path}/metadata.json"
        
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Parse last activity timestamp
                last_activity = datetime.fromisoformat(metadata["last_activity"]).timestamp()
                
                if current_time - last_activity > max_age_seconds:
                    session_id = metadata["session_id"]
                    
                    # Close if actively running
                    if session_id in session_manager.sessions:
                        await session_manager.close_session(session_id)
                    
                    # Move to archived folder
                    archived_dir = f"/opt/code-server/recordings/archived/session_{session_id}_{int(last_activity)}"
                    shutil.move(session_path, archived_dir)
                    
                    cleaned_sessions.append({
                        "session_id": session_id,
                        "last_activity": metadata["last_activity"],
                        "archived_to": archived_dir
                    })
            
            except Exception as e:
                continue  # Skip problematic sessions
    
    return {
        "status": "success",
        "max_age_hours": max_age_hours,
        "cleaned_sessions": cleaned_sessions,
        "total_cleaned": len(cleaned_sessions),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str):
    """
    Export session as downloadable zip file
    
    **Example:**
    ```bash
    curl -O http://100.95.89.72:8000/api/sessions/abc12345/export
    ```
    """
    import zipfile
    import tempfile
    
    session_dir = f"/opt/code-server/recordings/sessions/session_{session_id}"
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Create temporary zip file
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=f"_session_{session_id}.zip")
    
    with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(session_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, session_dir)
                zipf.write(file_path, arcname)
    
    return FileResponse(
        temp_zip.name,
        filename=f"session_{session_id}.zip",
        media_type="application/zip"
    )

if __name__ == "__main__":
    # Configuration
    # Default to 0.0.0.0 to allow Tailscale access, or use environment variable
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    print(f"Starting server on {host}:{port}")
    print("Tailscale IP: 100.95.89.72")
    print("Access via: http://100.95.89.72:8000")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )