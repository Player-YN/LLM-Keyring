"""
main.py — LLM-Keyring backend (FastAPI).

v0.2 changes from v0.1:
  - Security model: only shows keys in the managed whitelist (default view)
  - New /api/discover endpoint to scan for LLM keys already on the machine
  - New /api/adopt and /api/unadopt endpoints to manage the whitelist
  - /api/keys now operates ONLY on managed keys (OneDrive / PATH etc. hidden)

Run:
    python main.py
"""

from __future__ import annotations

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
    read_managed_env,
    set_user_env,
    delete_user_env,
    discover_llm_keys,
    adopt_key,
    unadopt_key,
    adopt_keys_bulk,
    is_managed,
    get_managed_keys,
)


# ============================================================
# Configuration
# ============================================================

HOST = "127.0.0.1"
PREFERRED_PORT = 8765
MAX_PORT_TRIES = 50
APP_NAME = "LLM-Keyring"
APP_VERSION = "0.2.0"
APP_TAGLINE = "Manage LLM API keys as OS env vars. Only what you mark."


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


class AdoptRequest(BaseModel):
    names: List[str]


class UnadoptRequest(BaseModel):
    name: str


# ============================================================
# Preset templates (24 entries)
# ============================================================

PRESET_TEMPLATES: List[Dict[str, str]] = [
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
    {"name": "OPENROUTER_API_KEY",      "provider": "OpenRouter",                    "category": "Aggregator"},
    {"name": "TOGETHER_API_KEY",        "provider": "Together AI",                   "category": "Aggregator"},
    {"name": "FIREWORKS_API_KEY",       "provider": "Fireworks AI",                  "category": "Aggregator"},
    {"name": "REPLICATE_API_TOKEN",     "provider": "Replicate",                     "category": "Aggregator"},
    {"name": "HF_TOKEN",                "provider": "Hugging Face Hub",              "category": "Aggregator"},
    {"name": "ANTHROPIC_VERTEX_API_KEY","provider": "Vertex AI (Claude)",            "category": "Aggregator"},
    {"name": "AZURE_OPENAI_API_KEY",    "provider": "Azure OpenAI",                  "category": "Aggregator"},
    {"name": "AWS_BEDROCK_API_KEY",     "provider": "AWS Bedrock",                   "category": "Aggregator"},
    {"name": "ANYSCALE_API_KEY",        "provider": "Anyscale Endpoints",            "category": "Aggregator"},
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
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        return base / "frontend"
    return Path(__file__).parent / "frontend"


FRONTEND_DIR = _frontend_dir()


@app.get("/")
async def index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=500, detail="Frontend not found")
    return FileResponse(index_file)


# ============================================================
# API endpoints
# ============================================================

@app.get("/api/keys")
async def list_managed_keys(q: Optional[str] = Query(None)):
    """List ONLY managed keys (the default view)."""
    env = read_managed_env()
    if q:
        q_lower = q.lower()
        env = {k: v for k, v in env.items() if q_lower in k.lower()}

    items = [
        {"name": name, "masked_value": _mask_value(value), "length": len(value)}
        for name, value in env.items()
    ]
    items.sort(key=lambda x: x["name"].upper())
    return {"items": items, "count": len(items), "view": "managed"}


@app.get("/api/discover")
async def discover():
    """Scan all user env vars and classify as LLM keys."""
    result = discover_llm_keys()
    # Strip value previews for skipped entries to avoid huge payloads
    return result


@app.get("/api/keys/{name}/value")
async def get_key_value(name: str):
    """Get the actual unmasked value of a managed key."""
    env = read_managed_env()
    if name not in env:
        raise HTTPException(status_code=404, detail=f"Managed key '{name}' not found")
    return {"name": name, "value": env[name]}


@app.post("/api/keys", status_code=201)
async def create_key(payload: KeyCreate):
    """Create a new env var + auto-add to managed whitelist."""
    if is_managed(payload.name):
        raise HTTPException(
            status_code=409,
            detail=f"Key '{payload.name}' is already managed. Use PUT to update.",
        )
    try:
        set_user_env(payload.name, payload.value)
    except (ValueError, NotImplementedError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": payload.name, "ok": True}


@app.put("/api/keys/{name}")
async def update_key(name: str, payload: KeyUpdate):
    """Update an existing managed env var."""
    if not is_managed(name):
        raise HTTPException(status_code=404, detail=f"Managed key '{name}' not found")
    try:
        set_user_env(name, payload.value)
    except (ValueError, NotImplementedError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "ok": True}


@app.delete("/api/keys/{name}")
async def delete_key(name: str):
    """Delete a managed env var + remove from whitelist."""
    if not is_managed(name):
        raise HTTPException(status_code=404, detail=f"Managed key '{name}' not found")
    deleted = delete_user_env(name)
    if not deleted:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"name": name, "ok": True}


@app.post("/api/adopt")
async def adopt(payload: AdoptRequest):
    """
    Adopt one or more keys into the managed whitelist.

    The env vars must already exist; this just marks them as "manage these".
    """
    result = adopt_keys_bulk(payload.names)
    return result


@app.post("/api/unadopt")
async def unadopt(payload: UnadoptRequest):
    """
    Remove a key from the managed whitelist. Does NOT delete the env var.

    After unadopting, the key becomes invisible in the Managed view but
    still exists in your environment. You can re-adopt it later.
    """
    removed = unadopt_key(payload.name)
    return {"name": payload.name, "unadopted": removed}


@app.get("/api/templates")
async def list_templates():
    return {"templates": PRESET_TEMPLATES}


@app.post("/api/import")
async def import_env(payload: EnvImport):
    """Import .env content. Each created key is auto-added to managed whitelist."""
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

        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]

        try:
            set_user_env(name, value)  # set_user_env auto-adds to managed
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
    """Export MANAGED env vars only (not the full environment)."""
    env = read_managed_env()
    lines = [
        "# Generated by LLM-Keyring",
        f"# Managed keys: {len(env)}",
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
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python": sys.version.split()[0],
        "frontend_dir": str(FRONTEND_DIR),
        "frozen": getattr(sys, "frozen", False),
        "managed_count": len(get_managed_keys()),
    }


# ============================================================
# Helpers
# ============================================================

def _mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def find_free_port(preferred: int, max_tries: int = MAX_PORT_TRIES) -> int:
    for port in range(preferred, preferred + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {preferred}–{preferred + max_tries - 1}")


def open_browser_when_ready(url: str, delay: float = 1.5):
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
    print(f"  Managed  : {len(get_managed_keys())} key(s)")
    print(f"  URL      : {url}")
    print()
    print("  Press Ctrl+C to stop the server.")
    print("=" * 64)
    print()

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