"""
main.py — LLM-Keyring backend (FastAPI).

Single-file FastAPI app that:
  - Serves the frontend at /
  - Provides REST API at /api/* for env var CRUD
  - Provides preset templates at /api/templates
  - Handles .env import/export
  - Auto-opens browser on startup
  - Detects port conflicts and picks the next free port

Run:
    python main.py

Or via the bundled start.bat / start.sh.

PyInstaller:
    pyinstaller --onefile --name llm-keyring --add-data "frontend;frontend" main.py
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from env_manager import (
    read_all_user_env,
    set_user_env,
    delete_user_env,
)


# ============================================================
# Configuration
# ============================================================

HOST = "127.0.0.1"          # localhost only — never expose to network
PREFERRED_PORT = 8765
MAX_PORT_TRIES = 50         # try 8765 → 8814
APP_NAME = "LLM-Keyring"
APP_VERSION = "0.1.0"
APP_TAGLINE = "Manage LLM API keys as OS env vars, from your browser."


# ============================================================
# Pydantic models
# ============================================================

class KeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    value: str = Field(..., min_length=1)


class KeyUpdate(BaseModel):
    value: str = Field(..., min_length=1)


class EnvImport(BaseModel):
    content: str


# ============================================================
# Preset templates (24 entries across 3 categories)
# ============================================================

PRESET_TEMPLATES: List[Dict[str, str]] = [
    # International cloud providers
    {"name": "OPENAI_API_KEY",          "provider": "OpenAI",                        "category": "International"},
    {"name": "ANTHROPIC_API_KEY",       "provider": "Anthropic (Claude)",            "category": "International"},
    {"name": "GOOGLE_API_KEY",          "provider": "Google Gemini",                 "category": "International"},
    {"name": "MISTRAL_API_KEY",         "provider": "Mistral AI",                    "category": "International"},
    {"name": "COHERE_API_KEY",          "provider": "Cohere",                        "category": "International"},
    {"name": "GROQ_API_KEY",            "provider": "Groq",                          "category": "International"},
    {"name": "PERPLEXITY_API_KEY",      "provider": "Perplexity",                    "category": "International"},
    {"name": "XAI_API_KEY",             "provider": "xAI (Grok)",                    "category": "International"},
    {"name": "DEEPSEEK_API_KEY",        "provider": "DeepSeek",                      "category": "International"},
    {"name": "MOONSHOT_API_KEY",        "provider": "Moonshot (Kimi)",               "category": "International"},

    # Aggregators / Routers
    {"name": "OPENROUTER_API_KEY",      "provider": "OpenRouter",                    "category": "Aggregator"},
    {"name": "TOGETHER_API_KEY",        "provider": "Together AI",                   "category": "Aggregator"},
    {"name": "FIREWORKS_API_KEY",       "provider": "Fireworks AI",                  "category": "Aggregator"},
    {"name": "REPLICATE_API_TOKEN",     "provider": "Replicate",                     "category": "Aggregator"},
    {"name": "HF_TOKEN",                "provider": "Hugging Face Hub",              "category": "Aggregator"},
    {"name": "ANTHROPIC_VERTEX_API_KEY","provider": "Vertex AI (Claude)",            "category": "Aggregator"},
    {"name": "AZURE_OPENAI_API_KEY",    "provider": "Azure OpenAI",                  "category": "Aggregator"},
    {"name": "AWS_BEDROCK_API_KEY",     "provider": "AWS Bedrock",                   "category": "Aggregator"},
    {"name": "ANYSCALE_API_KEY",        "provider": "Anyscale Endpoints",            "category": "Aggregator"},

    # Chinese aggregators
    {"name": "SILICONFLOW_API_KEY",     "provider": "硅基流动 (SiliconFlow)",        "category": "Chinese"},
    {"name": "ARK_API_KEY",             "provider": "火山方舟 (Ark) / Coding Plan",  "category": "Chinese"},
    {"name": "ZHIPUAI_API_KEY",         "provider": "智谱 BigModel",                 "category": "Chinese"},
    {"name": "QIANFAN_API_KEY",         "provider": "百度千帆",                       "category": "Chinese"},
    {"name": "DASHSCOPE_API_KEY",       "provider": "阿里 DashScope (通义千问)",      "category": "Chinese"},
]


# ============================================================
# App setup
# ============================================================

app = FastAPI(title=APP_NAME, version=APP_VERSION)


def _frontend_dir() -> Path:
    """
    Locate the frontend directory.

    Works in both dev mode (running from source) and PyInstaller bundle mode.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: frontend is unpacked at sys._MEIPASS/frontend
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        return base / "frontend"
    else:
        # Dev mode: frontend is sibling of main.py
        return Path(__file__).parent / "frontend"


FRONTEND_DIR = _frontend_dir()


@app.get("/")
async def index():
    """Serve the main HTML page."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Frontend not found at {index_file}. "
                   "If running from source, ensure 'frontend/index.html' exists. "
                   "If running from .exe, the bundle may be corrupted.",
        )
    return FileResponse(index_file)


# ============================================================
# API endpoints
# ============================================================

@app.get("/api/keys")
async def list_keys(q: Optional[str] = Query(None, description="Optional search filter")):
    """
    List all user-level env vars with values masked.

    Query params:
        q: Optional case-insensitive substring filter on variable name.
    """
    env = read_all_user_env()

    if q:
        q_lower = q.lower()
        env = {k: v for k, v in env.items() if q_lower in k.lower()}

    items = [
        {
            "name": name,
            "masked_value": _mask_value(value),
            "length": len(value),
        }
        for name, value in env.items()
    ]
    # Sort alphabetically (case-insensitive)
    items.sort(key=lambda x: x["name"].upper())
    return {"items": items, "count": len(items)}


@app.get("/api/keys/{name}/value")
async def get_key_value(name: str):
    """
    Get the actual unmasked value of a specific key.

    This endpoint exists so the frontend can fetch the value on-demand
    when the user clicks the eye icon. The list endpoint masks values
    for safety.
    """
    env = read_all_user_env()
    if name not in env:
        raise HTTPException(status_code=404, detail=f"Key '{name}' not found")
    return {"name": name, "value": env[name]}


@app.post("/api/keys", status_code=201)
async def create_key(payload: KeyCreate):
    """
    Create a new env var. Returns 409 if name already exists.
    """
    env = read_all_user_env()
    if payload.name in env:
        raise HTTPException(
            status_code=409,
            detail=f"Key '{payload.name}' already exists. Use PUT to update.",
        )
    try:
        set_user_env(payload.name, payload.value)
    except (ValueError, NotImplementedError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": payload.name, "ok": True}


@app.put("/api/keys/{name}")
async def update_key(name: str, payload: KeyUpdate):
    """
    Update an existing env var (creates it if it doesn't exist).
    """
    try:
        set_user_env(name, payload.value)
    except (ValueError, NotImplementedError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "ok": True}


@app.delete("/api/keys/{name}")
async def delete_key(name: str):
    """
    Delete an env var. Returns 404 if name doesn't exist.
    """
    deleted = delete_user_env(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{name}' not found")
    return {"name": name, "ok": True}


@app.get("/api/templates")
async def list_templates():
    """List all preset templates."""
    return {"templates": PRESET_TEMPLATES}


@app.post("/api/import")
async def import_env(payload: EnvImport):
    """
    Import .env content (KEY=VALUE per line).

    Handles:
      - Blank lines (skipped)
      - Comment lines starting with # (skipped)
      - Optional surrounding quotes on values (stripped)
      - Invalid lines without '=' (skipped with reason)
      - Per-line errors (recorded, doesn't abort batch)
    """
    created: List[str] = []
    skipped: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []

    for i, raw_line in enumerate(payload.content.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            skipped.append({"line": i, "content": line, "reason": "no '=' found"})
            continue

        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()

        # Strip surrounding quotes (single or double)
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]

        try:
            set_user_env(name, value)
            created.append(name)
        except Exception as e:
            errors.append({"line": i, "content": line, "reason": str(e)})

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "error_count": len(errors),
    }


@app.post("/api/export", response_class=PlainTextResponse)
async def export_env():
    """
    Export all user env vars as .env content (KEY=VALUE per line).

    Values containing special chars (spaces, quotes, #, backslashes) are
    double-quoted with internal quotes escaped.
    """
    env = read_all_user_env()
    lines = [
        "# Generated by LLM-Keyring",
        f"# Total: {len(env)} variables",
        "# Use with: source .env  (bash)  /  set -a; . ./.env; set +a  (POSIX)",
        "",
    ]
    for name, value in sorted(env.items()):
        if any(c in value for c in [' ', '"', "'", '#', '\\']):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'{name}="{escaped}"')
        else:
            lines.append(f'{name}={value}')
    return "\n".join(lines)


@app.get("/api/info")
async def info():
    """Return platform and app info (useful for the frontend footer)."""
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python": sys.version.split()[0],
        "frontend_dir": str(FRONTEND_DIR),
        "frozen": getattr(sys, "frozen", False),
    }


# ============================================================
# Helpers
# ============================================================

def _mask_value(value: str) -> str:
    """
    Mask sensitive value for list display.

    Examples:
        "sk-proj-abc123xyz"  →  "sk-p****xyz"
        "short"              →  "****"
        ""                   →  ""
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def find_free_port(preferred: int, max_tries: int = MAX_PORT_TRIES) -> int:
    """
    Find a free TCP port starting from `preferred`.

    There is a small race window between checking and binding — another process
    could grab the port in between. uvicorn will retry on its own. For a
    desktop app this is acceptable.
    """
    for port in range(preferred, preferred + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range {preferred}–{preferred + max_tries - 1}. "
        "Close some apps or restart your computer."
    )


def open_browser_when_ready(url: str, delay: float = 1.5):
    """
    Open the default browser to `url` after `delay` seconds.

    Runs in a daemon thread so it doesn't block the main process. The delay
    gives uvicorn time to start accepting connections.
    """
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


# ============================================================
# Entry point
# ============================================================

def main():
    """Start the LLM-Keyring server."""
    port = find_free_port(PREFERRED_PORT)
    url = f"http://{HOST}:{port}"

    print()
    print("=" * 64)
    print(f"  {APP_NAME} v{APP_VERSION}")
    print("=" * 64)
    print(f"  {APP_TAGLINE}")
    print()
    print(f"  Platform : {platform.system()} {platform.release()}")
    print(f"  Python   : {sys.version.split()[0]}")
    print(f"  URL      : {url}")
    print()
    print("  Press Ctrl+C to stop the server.")
    print("=" * 64)
    print()

    # Open browser after a short delay (lets server bind first)
    open_browser_when_ready(url)

    uvicorn.run(
        app,
        host=HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()