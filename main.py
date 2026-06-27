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
from chat import probe_capabilities, stream_chat, fetch_models
from fastapi.responses import StreamingResponse


# ============================================================
# Provider metadata (key name → default base URL + display name)
# Used by /api/chat and /api/test to know where to send requests
# without making the user type the endpoint every time.
# ============================================================

PROVIDER_BASE_URLS: Dict[str, str] = {
    # International
    "OPENAI_API_KEY":           "https://api.openai.com/v1",
    "ANTHROPIC_API_KEY":        "https://api.anthropic.com/v1",
    "GOOGLE_API_KEY":           "https://generativelanguage.googleapis.com/v1beta",
    "MISTRAL_API_KEY":          "https://api.mistral.ai/v1",
    "COHERE_API_KEY":           "https://api.cohere.ai/v1",
    "GROQ_API_KEY":             "https://api.groq.com/openai/v1",
    "PERPLEXITY_API_KEY":       "https://api.perplexity.ai",
    "XAI_API_KEY":              "https://api.x.ai/v1",
    "DEEPSEEK_API_KEY":         "https://api.deepseek.com/v1",
    "MOONSHOT_API_KEY":         "https://api.moonshot.cn/v1",
    # Aggregators (all OpenAI-compatible)
    "OPENROUTER_API_KEY":       "https://openrouter.ai/api/v1",
    "TOGETHER_API_KEY":         "https://api.together.xyz/v1",
    "FIREWORKS_API_KEY":        "https://api.fireworks.ai/inference/v1",
    "REPLICATE_API_TOKEN":      "https://api.replicate.com/v1",
    "HF_TOKEN":                 "https://router.huggingface.co/v1",
    "ANTHROPIC_VERTEX_API_KEY": "https://us-central1-aiplatform.googleapis.com/v1",
    "AZURE_OPENAI_API_KEY":     "",  # User must provide
    "AWS_BEDROCK_API_KEY":      "",  # User must provide
    "ANYSCALE_API_KEY":         "https://api.endpoints.anyscale.com/v1",
    # Chinese
    "SILICONFLOW_API_KEY":      "https://api.siliconflow.cn/v1",
    "ARK_API_KEY":              "https://ark.cn-beijing.volces.com/api/v3",
    "ZHIPUAI_API_KEY":          "https://open.bigmodel.cn/api/paas/v4",
    "QIANFAN_API_KEY":          "https://qianfan.baidubce.com/v2",
    "DASHSCOPE_API_KEY":        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # Agnes (free, multimodal, Singapore)
    "AGNES_API_KEY":            "https://apihub.agnes-ai.com/v1",
}

# Common model hints per provider (used to populate the model dropdown
# when /v1/models is not available or empty)
PROVIDER_DEFAULT_MODELS: Dict[str, List[str]] = {
    "OPENAI_API_KEY":     ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "ANTHROPIC_API_KEY":  ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
    "GOOGLE_API_KEY":     ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    "GROQ_API_KEY":       ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "DEEPSEEK_API_KEY":   ["deepseek-chat", "deepseek-reasoner"],
    "OPENROUTER_API_KEY": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-70b-instruct"],
    "MOONSHOT_API_KEY":   ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    "SILICONFLOW_API_KEY": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3", "Pro/Qwen/Qwen2-7B-Instruct"],
    "ARK_API_KEY":        ["doubao-pro-32k", "doubao-lite-32k"],
    "DASHSCOPE_API_KEY":  ["qwen-plus", "qwen-turbo", "qwen-max"],
    "ZHIPUAI_API_KEY":    ["glm-4-plus", "glm-4-flash", "glm-4"],
    "AGNES_API_KEY":      ["agnes-2.0-flash", "agnes-1.5-flash"],
}


def _resolve_base_url(name: str, override: Optional[str]) -> str:
    """Return the base URL for a managed key. User override wins, else preset.

    Match priority:
      1. Exact match
      2. Case-insensitive exact match ("Agnes" → "AGNES_API_KEY" if exact keys differ)
      3. Case-insensitive prefix match ("Agnes" → "AGNES_API_KEY" since
         AGNES starts with "AGNES" / "Agnes" starts with "AGNES")
      4. Return "" (caller raises 400)
    """
    if override:
        return override.rstrip("/")
    if name in PROVIDER_BASE_URLS:
        return PROVIDER_BASE_URLS[name]
    # Case-insensitive exact
    upper = name.upper()
    for k, v in PROVIDER_BASE_URLS.items():
        if k.upper() == upper:
            return v
    # Case-insensitive prefix (e.g., "Agnes" matches "AGNES_API_KEY")
    for k, v in PROVIDER_BASE_URLS.items():
        if k.upper().startswith(upper + "_") or upper.startswith(k.upper().rstrip("_") + "_"):
            return v
    return ""


def _resolve_default_models(name: str) -> List[str]:
    """Return default model list for a key, with case-insensitive matching."""
    if name in PROVIDER_DEFAULT_MODELS:
        return PROVIDER_DEFAULT_MODELS[name]
    upper = name.upper()
    for k, v in PROVIDER_DEFAULT_MODELS.items():
        if k.upper() == upper:
            return v
    for k, v in PROVIDER_DEFAULT_MODELS.items():
        if k.upper().startswith(upper + "_") or upper.startswith(k.upper().rstrip("_") + "_"):
            return v
    return []


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


class ChatRequest(BaseModel):
    name: str = Field(..., description="Managed key name (e.g. 'AGNES_API_KEY')")
    base_url: Optional[str] = Field(None, description="Override base URL; defaults to preset")
    model: str = Field(..., description="Model name to use")
    messages: List[Dict] = Field(..., description="OpenAI-style messages array")
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class TestRequest(BaseModel):
    name: str = Field(..., description="Managed key name to test")
    base_url: Optional[str] = Field(None, description="Override base URL")


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
    {"name": "AGNES_API_KEY",            "provider": "Agnes AI (新加坡全模态,免费)",     "category": "International"},
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
    """
    Export MANAGED env vars as .env content with real plaintext values.

    This is the explicit purpose of this endpoint — to give the user a file
    they can `source` or use with `--env-file` for Docker / CI / migration.

    The file includes a WARNING header reminding the user not to commit it.
    """
    env = read_managed_env()
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# ============================================================",
        "# WARNING: This file contains REAL API keys in plaintext.",
        "# Treat it like a password. Do NOT commit to git.",
        "# Add '*.env' to your .gitignore before using.",
        f"# Generated by LLM-Keyring on {timestamp}",
        f"# Keys: {len(env)}",
        "# ============================================================",
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
# Chat + Test endpoints
# ============================================================

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Stream a chat completion (Server-Sent Events).

    Looks up the managed key value, resolves base URL, then proxies
    the request as a streaming response so the browser can render
    tokens as they arrive.
    """
    env = read_managed_env()
    if req.name not in env:
        raise HTTPException(status_code=404, detail=f"Managed key '{req.name}' not found")

    api_key = env[req.name]
    base_url = _resolve_base_url(req.name, req.base_url)
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No known base URL for '{req.name}'. "
                f"Pass 'base_url' in the request body, or add it to PROVIDER_BASE_URLS in main.py."
            ),
        )

    return StreamingResponse(
        stream_chat(
            key=api_key,
            base_url=base_url,
            model=req.model,
            messages=req.messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx-style buffering
        },
    )


@app.post("/api/test")
async def test_key(req: TestRequest):
    """
    Probe a managed key for which endpoints it can access.
    Returns a capability matrix for the frontend to display.
    """
    env = read_managed_env()
    if req.name not in env:
        raise HTTPException(status_code=404, detail=f"Managed key '{req.name}' not found")

    api_key = env[req.name]
    base_url = _resolve_base_url(req.name, req.base_url)
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No known base URL for '{req.name}'. "
                f"Pass 'base_url' in the request body."
            ),
        )

    result = await probe_capabilities(api_key, base_url)

    # Also fetch model list if the /models endpoint is up
    models = []
    if any(r["name"] == "models" and r["supported"] for r in result["results"]):
        models = await fetch_models(api_key, base_url)
    if not models:
        # Fall back to the static defaults for this provider
        models = _resolve_default_models(req.name)

    result["models"] = models
    return result


@app.get("/api/providers")
async def list_providers():
    """Return the list of known provider presets (for the chat tab dropdown)."""
    providers = []
    for preset in PRESET_TEMPLATES:
        name = preset["name"]
        if name in PROVIDER_BASE_URLS or name in PROVIDER_DEFAULT_MODELS:
            providers.append({
                "name": name,
                "provider": preset["provider"],
                "category": preset["category"],
                "base_url": PROVIDER_BASE_URLS.get(name, ""),
                "default_models": _resolve_default_models(name),
            })
    return {"providers": providers}


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