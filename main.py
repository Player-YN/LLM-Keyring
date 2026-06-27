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
    get_managed_keys_full,
    get_managed_key,
    update_binding,
    add_managed_key,
    ManagedKey,
)
from providers import PROVIDERS, get_provider_by_id, get_providers_by_category
from chat import probe_capabilities, stream_chat, fetch_models
from fastapi.responses import StreamingResponse


# ============================================================
# Provider binding resolution
# ============================================================
#
# The base URL / model for a managed key comes from the user's binding
# (stored in managed_keys.json). If the binding is missing, we fall back
# to the provider's preset default using the binding's "provider" name,
# or — last resort — to looking up by key name in PROVIDERS.
# ============================================================


def _resolve_base_url(name: str, override: Optional[str]) -> str:
    """
    Return the base URL for a managed key.

    Priority:
      1. Caller-supplied override (request body)
      2. User's persisted binding (managed_keys.json)
      3. Preset default from PROVIDERS by the binding's "provider" name
      4. Preset default by the key NAME matching a provider id (legacy fallback)
      5. Return "" (caller raises 400)
    """
    if override:
        return override.rstrip("/")

    # 2. User's explicit binding (this is the v2 contract)
    binding = get_managed_key(name)
    if binding and binding.base_url:
        return binding.base_url

    # 3. Fall back: if binding exists with provider name, look up its preset URL
    if binding and binding.provider:
        provider = get_provider_by_id(binding.provider)
        if provider and provider["base_url"]:
            return provider["base_url"]

    # 4. Legacy fallback: match by key name to a provider id
    upper = name.upper()
    for p in PROVIDERS:
        if p["id"].upper() == upper and p["base_url"]:
            return p["base_url"]

    return ""


def _resolve_default_models(name: str) -> List[str]:
    """
    Return default model hints for a managed key.

    Priority:
      1. User's binding's default_model (single string, returned as [str])
      2. Preset models by binding.provider
      3. Preset models by key name (legacy fallback)
      4. Empty list
    """
    binding = get_managed_key(name)
    if binding:
        if binding.default_model:
            return [binding.default_model]
        if binding.provider:
            provider = get_provider_by_id(binding.provider)
            if provider:
                return list(provider["models"])

    upper = name.upper()
    for p in PROVIDERS:
        if p["id"].upper() == upper:
            return list(p["models"])

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
    provider: str = Field("", description="Provider ID from /api/providers (e.g. 'OPENAI_API_KEY')")
    base_url: str = Field("", description="Override base URL; empty = use provider preset")
    default_model: str = Field("", description="Default model for this key")


class KeyUpdate(BaseModel):
    value: str = Field(..., min_length=1)
    provider: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None


class BindingUpdate(BaseModel):
    """Update only the provider binding for an existing managed key."""
    provider: str = Field("", description="Provider ID")
    base_url: str = Field("", description="Base URL (can override the preset)")
    default_model: str = Field("", description="Default model")


class EnvImport(BaseModel):
    content: str


class AdoptItem(BaseModel):
    name: str
    provider: str = ""
    base_url: str = ""
    default_model: str = ""


class AdoptRequest(BaseModel):
    """Adopt one or more keys with optional provider bindings."""
    items: List[AdoptItem] = Field(default_factory=list)
    # Legacy support: allow plain list of names (no binding)
    names: Optional[List[str]] = None


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
# Preset templates — derived from providers.py (single source of truth)
# ============================================================

def _preset_templates() -> List[Dict[str, str]]:
    """Convert the providers registry into the preset shape used by the UI."""
    return [
        {"name": p["id"], "provider": p["name"], "category": p["category"]}
        for p in PROVIDERS
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
    """List ONLY managed keys (the default view), with provider binding info."""
    env = read_managed_env()
    if q:
        q_lower = q.lower()
        env = {k: v for k, v in env.items() if q_lower in k.lower()}

    # Build items with binding info
    items = []
    for name, value in env.items():
        binding = get_managed_key(name)
        provider_id = binding.provider if binding else ""
        provider_name = ""
        if provider_id:
            # Resolve provider id → display name (e.g. "DEEPSEEK_API_KEY" → "DeepSeek")
            p = get_provider_by_id(provider_id)
            if p:
                provider_name = p["name"]
        items.append({
            "name": name,
            "masked_value": _mask_value(value),
            "length": len(value),
            "provider": provider_id,
            "provider_name": provider_name,  # NIT-1: human-readable name for UI
            "base_url": binding.base_url if binding else "",
            "default_model": binding.default_model if binding else "",
            "has_binding": binding.has_binding() if binding else False,
        })
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
    """
    Create a new env var + add to managed whitelist, optionally with provider binding.

    The binding fields (provider, base_url, default_model) are optional but
    recommended — they let the Chat tab auto-fill the configuration when
    this key is selected. If base_url is omitted but a provider is given,
    the provider's preset base URL is used.
    """
    if is_managed(payload.name):
        raise HTTPException(
            status_code=409,
            detail=f"Key '{payload.name}' is already managed. Use PUT to update.",
        )
    try:
        set_user_env(payload.name, payload.value)
    except (ValueError, NotImplementedError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Always add to the managed whitelist (one write, not two). The CRIT-3
    # fix removed set_user_env's implicit auto-add; this is the single point
    # that now handles whitelist membership. The binding fields are optional
    # (empty strings are valid — user can configure them later).
    resolved_url = payload.base_url
    if not resolved_url and payload.provider:
        provider = get_provider_by_id(payload.provider)
        if provider:
            resolved_url = provider["base_url"]
    add_managed_key(
        payload.name,
        provider=payload.provider,
        base_url=resolved_url,
        default_model=payload.default_model,
    )

    return {"name": payload.name, "ok": True}


@app.put("/api/keys/{name}")
async def update_key(name: str, payload: KeyUpdate):
    """Update an existing managed env var + optionally its binding."""
    if not is_managed(name):
        raise HTTPException(status_code=404, detail=f"Managed key '{name}' not found")
    try:
        set_user_env(name, payload.value)
    except (ValueError, NotImplementedError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update binding if any binding field was provided
    if payload.provider is not None or payload.base_url is not None or payload.default_model is not None:
        try:
            current = get_managed_key(name)
            new_provider = payload.provider if payload.provider is not None else (current.provider if current else "")
            new_url = payload.base_url if payload.base_url is not None else (current.base_url if current else "")
            new_model = payload.default_model if payload.default_model is not None else (current.default_model if current else "")
            update_binding(name, new_provider, new_url, new_model)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return {"name": name, "ok": True}


@app.delete("/api/keys/{name}")
async def delete_key(name: str):
    """Delete a managed env var + remove from whitelist (and its binding)."""
    if not is_managed(name):
        raise HTTPException(status_code=404, detail=f"Managed key '{name}' not found")
    deleted = delete_user_env(name)
    if not deleted:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"name": name, "ok": True}


@app.put("/api/keys/{name}/binding")
async def set_binding(name: str, payload: BindingUpdate):
    """
    Set or update the provider binding for a managed key (without changing the value).

    This is the "edit binding" endpoint — used by the Chat tab when it
    needs to set up a provider for the first time, and by the Managed
    view's binding-edit affordance.
    """
    if not is_managed(name):
        raise HTTPException(status_code=404, detail=f"Managed key '{name}' not found")
    try:
        # If base_url is empty but provider is given, resolve from preset
        resolved_url = payload.base_url
        if not resolved_url and payload.provider:
            provider = get_provider_by_id(payload.provider)
            if provider:
                resolved_url = provider["base_url"]
        binding = update_binding(name, payload.provider, resolved_url, payload.default_model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "name": name,
        "provider": binding.provider,
        "base_url": binding.base_url,
        "default_model": binding.default_model,
        "ok": True,
    }


@app.post("/api/adopt")
async def adopt(payload: AdoptRequest):
    """
    Adopt one or more keys into the managed whitelist, each with optional
    provider binding.

    Body shapes accepted:
      - New:   {"items": [{"name": "X", "provider": "DEEPSEEK_API_KEY", "base_url": "..."}]}
      - Legacy:{"names": ["X", "Y"]}  (no binding — user must configure later)

    The env vars must already exist; this just marks them as "manage these".
    """
    if payload.items:
        # New format: list of items, each with optional binding
        items_for_bulk = [item.model_dump() for item in payload.items]
        result = adopt_keys_bulk(items_for_bulk)
    elif payload.names:
        # Legacy format: plain list of names
        items_for_bulk = [{"name": n} for n in payload.names]
        result = adopt_keys_bulk(items_for_bulk)
    else:
        result = {"adopted": [], "skipped": [], "adopted_count": 0, "skipped_count": 0}
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
    """List preset template stubs (name + provider + category) for the Add UI."""
    return {"templates": _preset_templates()}


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
            set_user_env(name, value)
            add_managed_key(name)  # explicit add (no auto-add in set_user_env anymore)
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
                f"Pass 'base_url' in the request body, or set up a provider "
                f"binding for this key via the Managed view (click the link icon)."
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
    """
    Return the full provider catalog (for Add modal + Chat tab dropdowns +
    binding-edit UI). Grouped by category for easier rendering.
    """
    grouped = get_providers_by_category()
    return {
        "providers": list(PROVIDERS),
        "by_category": grouped,
    }


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