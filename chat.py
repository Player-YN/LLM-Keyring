"""
chat.py — Chat / capability-probe helpers for LLM-Keyring.

Two responsibilities:

  1. `probe_capabilities(key, base_url)` — given an API key and the provider's
     base URL, find out which endpoints the key can access. Used by the
     "Test this key" feature to show the user what their key can do.

  2. `stream_chat(key, base_url, model, messages)` — a generator that
     yields token chunks from a chat-completions endpoint that supports
     OpenAI-style streaming. Used by the chat tab.

Both functions are designed to be:
  - Provider-agnostic (work with any OpenAI-compatible endpoint)
  - Fail-soft (each probe is independent; one failure doesn't break the rest)
  - No external dependencies beyond `httpx` (already a FastAPI dep)
"""

from __future__ import annotations

import json
from typing import AsyncGenerator, Dict, List, Optional

import httpx


# ============================================================
# Capability probing
# ============================================================

# Each probe: (name, label, method, path, json_body)
# 200 = supported; 4xx (non-401) = unsupported; 401 = auth issue (signal!)
# 404/405 = endpoint doesn't exist
PROBES = [
    {
        "name": "chat",
        "label": "Chat completions",
        "method": "POST",
        "path": "/chat/completions",
        "body": {
            "model": "auto",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        "needs_model": True,
    },
    {
        "name": "models",
        "label": "List models",
        "method": "GET",
        "path": "/models",
        "body": None,
        "needs_model": False,
    },
    {
        "name": "images",
        "label": "Image generation",
        "method": "POST",
        "path": "/images/generations",
        "body": {
            "model": "auto",
            "prompt": "test",
            "size": "256x256",
        },
        "needs_model": True,
    },
    {
        "name": "embeddings",
        "label": "Embeddings",
        "method": "POST",
        "path": "/embeddings",
        "body": {
            "model": "auto",
            "input": "test",
        },
        "needs_model": True,
    },
    {
        "name": "audio_speech",
        "label": "Text-to-speech",
        "method": "POST",
        "path": "/audio/speech",
        "body": {
            "model": "auto",
            "input": "test",
            "voice": "alloy",
        },
        "needs_model": True,
    },
    {
        "name": "audio_transcription",
        "label": "Speech-to-text",
        "method": "POST",
        "path": "/audio/transcriptions",
        "body": None,  # multipart, skipped
        "needs_model": True,
        "skip": True,  # Can't easily probe without a real audio file
    },
    {
        "name": "videos",
        "label": "Video generation",
        "method": "POST",
        "path": "/videos",
        "body": {
            "model": "auto",
            "prompt": "test",
        },
        "needs_model": True,
    },
    {
        "name": "responses",
        "label": "Responses (OpenAI new)",
        "method": "POST",
        "path": "/responses",
        "body": {
            "model": "auto",
            "input": "ping",
        },
        "needs_model": True,
    },
]


async def probe_capabilities(
    key: str,
    base_url: str,
    timeout: float = 8.0,
) -> Dict:
    """
    Probe a provider for which endpoints this API key can access.

    Args:
        key: The API key value
        base_url: e.g. "https://apihub.agnes-ai.com/v1"
        timeout: Per-request timeout in seconds

    Returns:
        Dict with:
          - base_url: The base URL probed
          - results: List of {name, label, status, code, supported, error}
          - supported_count: number of supported capabilities
          - summary: one-line human summary
    """
    base_url = base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    results = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        for probe in PROBES:
            if probe.get("skip"):
                results.append({
                    "name": probe["name"],
                    "label": probe["label"],
                    "status": "skipped",
                    "code": None,
                    "supported": False,
                    "error": "Requires multipart upload (audio file); not probe-able",
                })
                continue

            url = f"{base_url}{probe['path']}"
            try:
                if probe["method"] == "GET":
                    r = await client.get(url, headers=headers)
                else:
                    r = await client.post(url, headers=headers, json=probe["body"])

                # Determine "supported" status
                if r.status_code in (200, 201):
                    supported = True
                    err = None
                elif r.status_code in (401, 403):
                    supported = False
                    err = f"Auth failed ({r.status_code}) — wrong key or scope"
                elif r.status_code in (404, 405):
                    supported = False
                    err = f"Not supported ({r.status_code})"
                elif r.status_code in (400, 422):
                    # Bad request — usually means endpoint exists but body was wrong
                    # For probes with model="auto", 400 is common if the model name
                    # isn't valid. Try a model-less request to disambiguate.
                    supported = True  # Be optimistic; endpoint exists
                    err = f"Endpoint exists (400/422 — body needs adjustment)"
                elif r.status_code in (429, 500, 502, 503, 504):
                    # Rate limit or server error — endpoint likely exists
                    supported = True
                    err = f"Endpoint exists ({r.status_code})"
                else:
                    supported = False
                    err = f"HTTP {r.status_code}"

                results.append({
                    "name": probe["name"],
                    "label": probe["label"],
                    "status": "ok" if supported else "fail",
                    "code": r.status_code,
                    "supported": supported,
                    "error": err,
                })
            except httpx.TimeoutException:
                results.append({
                    "name": probe["name"],
                    "label": probe["label"],
                    "status": "timeout",
                    "code": None,
                    "supported": False,
                    "error": f"Timed out after {timeout}s",
                })
            except Exception as e:
                results.append({
                    "name": probe["name"],
                    "label": probe["label"],
                    "status": "error",
                    "code": None,
                    "supported": False,
                    "error": f"{type(e).__name__}: {e}",
                })

    supported_count = sum(1 for r in results if r["supported"])
    if supported_count == 0:
        summary = "No capabilities detected. Check the base URL and key."
    elif supported_count == 1:
        cap = next(r for r in results if r["supported"])["label"]
        summary = f"Supports: {cap}"
    else:
        caps = [r["label"] for r in results if r["supported"]]
        summary = f"Supports {supported_count} capabilities: {', '.join(caps)}"

    return {
        "base_url": base_url,
        "results": results,
        "supported_count": supported_count,
        "summary": summary,
    }


# ============================================================
# Streaming chat
# ============================================================

async def stream_chat(
    key: str,
    base_url: str,
    model: str,
    messages: List[Dict],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    timeout: float = 60.0,
) -> AsyncGenerator[str, None]:
    """
    Stream a chat completion from an OpenAI-compatible endpoint.

    Yields SSE-formatted lines: "data: {json}

"
    Final message: "data: [DONE]

"

    Each yielded chunk is the raw SSE data line, ready to be forwarded
    to the browser.
    """
    base_url = base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                # Try to read error body
                err_text = await resp.aread()
                err_msg = f"HTTP {resp.status_code}: {err_text.decode('utf-8', errors='replace')[:500]}"
                yield f"data: {json.dumps({'error': err_msg})}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    # Forward the raw chunk as-is
                    yield f"data: {chunk}\n\n"


async def fetch_models(key: str, base_url: str, timeout: float = 10.0) -> List[str]:
    """
    Try to fetch a list of available model names from a provider's /models endpoint.

    Returns empty list if the endpoint doesn't exist or returns an error.
    """
    base_url = base_url.rstrip("/")
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return []
            data = r.json()
            models = data.get("data", [])
            return [m.get("id", m) if isinstance(m, dict) else str(m) for m in models]
    except Exception:
        return []