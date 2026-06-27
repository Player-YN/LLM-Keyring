"""
env_manager.py — Cross-platform User-level environment variable management,
plus LLM-key classifier and managed-keys whitelist.

Three responsibilities:

  1. **Env var CRUD** (Windows / macOS / Linux)
     - Windows: triple-write (registry + SetEnvironmentVariableW + broadcast)
     - macOS/Linux: stub (read-only in v0.1)

  2. **LLM-key classifier**
     - Detects which env vars look like LLM API keys
     - Three confidence levels: high / medium / low
     - Blacklist excludes system / non-LLM vars (OneDrive, PATH, etc.)

  3. **Managed-keys whitelist**
     - Persisted in `managed_keys.json` next to the executable
     - Only keys in this list appear in the Managed view
     - Added when user creates / adopts / imports a key

This split is the security model: the panel can ONLY touch keys the user
explicitly marked as "this is mine, manage it for me". Everything else in
the user's environment stays invisible and untouchable.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set


SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"


# ============================================================
# Managed-keys whitelist persistence  (v2 schema)
# ============================================================
#
# v1 (legacy):  {"keys": ["AGNES_API_KEY", "MINIMAX_API_KEY"]}
# v2 (current): {"version": 2, "keys": [
#                   {"name": "AGNES_API_KEY", "provider": "Agnes AI",
#                    "base_url": "https://apihub.agnes-ai.com/v1",
#                    "default_model": "agnes-2.0-flash",
#                    "added_at": "2026-06-27T08:00:00Z"}
#                 ]}
#
# The v2 schema captures the user's **explicit provider binding** for each
# managed key. This binding is set once (when the user first configures the
# key) and persists permanently. It's tied to the key NAME, not the key
# VALUE, so rotating the API secret does NOT break the binding.
# ============================================================


def _managed_keys_path() -> Path:
    """
    Locate the managed-keys JSON file.

    Layout:
        dev mode:   <repo>/managed_keys.json
        bundled:    %APPDATA%/LLM-Keyring/managed_keys.json  (Windows)
                    ~/Library/Application Support/LLM-Keyring/  (macOS)
                    ~/.config/llm-keyring/                     (Linux)

    The bundled layout keeps user state out of the .exe directory and
    survives reinstalls.
    """
    if getattr(sys, "frozen", False):
        # Bundled app — store in user data dir
        if SYSTEM == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home())) / "LLM-Keyring"
        elif SYSTEM == "Darwin":
            base = Path.home() / "Library" / "Application Support" / "LLM-Keyring"
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "llm-keyring"
        base.mkdir(parents=True, exist_ok=True)
        return base / "managed_keys.json"
    else:
        # Dev mode — store next to main.py
        return Path(__file__).parent / "managed_keys.json"


class ManagedKey:
    """A single managed-key entry (v2 schema)."""

    __slots__ = ("name", "provider", "base_url", "default_model", "added_at")

    def __init__(
        self,
        name: str,
        provider: str = "",
        base_url: str = "",
        default_model: str = "",
        added_at: Optional[str] = None,
    ):
        self.name = name
        self.provider = provider
        self.base_url = base_url
        self.default_model = default_model
        self.added_at = added_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ManagedKey":
        return cls(
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            base_url=data.get("base_url", ""),
            default_model=data.get("default_model", ""),
            added_at=data.get("added_at"),
        )

    def has_binding(self) -> bool:
        """True if the user has set a provider binding for this key."""
        return bool(self.base_url)


def _load_managed_keys_raw() -> List[ManagedKey]:
    """
    Read the managed-keys file, handling both v1 (legacy list) and v2 (dict)
    schemas. v1 files are auto-migrated to v2 on the next save (binding
    fields are left empty — user must configure them in the UI).

    Returns a list of ManagedKey. If the file is missing or corrupt, returns [].
    """
    path = _managed_keys_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt file — start fresh, don't lose user's env vars
        return []

    keys_field = data.get("keys", [])
    out: List[ManagedKey] = []

    # v2 schema: list of dicts
    if isinstance(keys_field, list) and keys_field and isinstance(keys_field[0], dict):
        for entry in keys_field:
            if isinstance(entry, dict) and entry.get("name"):
                out.append(ManagedKey.from_dict(entry))
    # v1 schema: list of strings (just names, no binding)
    elif isinstance(keys_field, list):
        for name in keys_field:
            if isinstance(name, str) and name:
                out.append(ManagedKey(name=name))  # binding fields empty

    return out


def _save_managed_keys_raw(keys: List[ManagedKey]) -> None:
    """Persist the managed-keys list to disk in v2 schema format."""
    path = _managed_keys_path()
    try:
        payload = {
            "version": 2,
            "keys": [k.to_dict() for k in keys],
        }
        # Sort by name (case-insensitive) for stable file diffs
        payload["keys"].sort(key=lambda x: x["name"].upper())
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError:
        # If we can't write (read-only fs, etc.), the panel still works in-memory
        pass


# ============================================================
# Public whitelist API
# ============================================================

def get_managed_keys() -> Set[str]:
    """Get the set of managed key NAMES (legacy interface, still used in many places)."""
    return {k.name for k in _load_managed_keys_raw()}


def get_managed_keys_full() -> List[ManagedKey]:
    """Get the full list of managed keys with their bindings."""
    return _load_managed_keys_raw()


def get_managed_key(name: str) -> Optional[ManagedKey]:
    """Get a single managed key by name (including binding info)."""
    for k in _load_managed_keys_raw():
        if k.name == name:
            return k
    return None


def is_managed(name: str) -> bool:
    """Check if a key is in the managed whitelist."""
    return name in get_managed_keys()


def add_managed_key(
    name: str,
    provider: str = "",
    base_url: str = "",
    default_model: str = "",
) -> ManagedKey:
    """
    Add (or update) a key in the managed whitelist with provider binding.

    If the key already exists, only the provided binding fields are updated
    (others preserved). Returns the resulting ManagedKey.

    This is the primary API for setting provider bindings. Called when:
      - User adds a new key with provider info
      - User adopts a key with provider info (Discover)
      - User edits an existing key's binding
    """
    keys = _load_managed_keys_raw()
    existing = next((k for k in keys if k.name == name), None)
    if existing:
        # Update only the fields that were explicitly provided (non-empty)
        if provider:
            existing.provider = provider
        if base_url:
            existing.base_url = base_url
        if default_model:
            existing.default_model = default_model
        result = existing
    else:
        result = ManagedKey(
            name=name,
            provider=provider,
            base_url=base_url,
            default_model=default_model,
        )
        keys.append(result)

    _save_managed_keys_raw(keys)
    return result


def update_binding(name: str, provider: str, base_url: str, default_model: str = "") -> ManagedKey:
    """
    Set / update the provider binding for an already-managed key.

    Unlike add_managed_key(), this REPLACES the binding fields unconditionally
    (used by the Edit-binding UI). The key must already be managed.

    Raises ValueError if the key is not managed.
    """
    keys = _load_managed_keys_raw()
    for k in keys:
        if k.name == name:
            k.provider = provider
            k.base_url = base_url
            k.default_model = default_model
            _save_managed_keys_raw(keys)
            return k
    raise ValueError(f"Key '{name}' is not managed")


def remove_managed_key(name: str) -> None:
    """Remove a key from the managed whitelist. Does NOT delete the env var."""
    keys = _load_managed_keys_raw()
    keys = [k for k in keys if k.name != name]
    _save_managed_keys_raw(keys)


# ============================================================
# Windows env var CRUD (registry + kernel session + broadcast)
# ============================================================

def _windows_read_all_user_env() -> Dict[str, str]:
    """Read all User-level env vars from HKCU\\Environment."""
    import winreg

    env_vars: Dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if isinstance(value, str):
                        env_vars[name] = value
                    i += 1
                except OSError:
                    break
    except FileNotFoundError:
        pass
    return env_vars


def _windows_set_user_env(name: str, value: str) -> None:
    """Triple-write: registry + SetEnvironmentVariableW + WM_SETTINGCHANGE."""
    import ctypes
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
        0,
        winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    )
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(key)

    ctypes.windll.kernel32.SetEnvironmentVariableW(name, value)
    _broadcast_setting_change()


def _windows_delete_user_env(name: str) -> bool:
    """Triple-delete: registry + SetEnvironmentVariableW(NULL) + broadcast."""
    import ctypes
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return False

    deleted = False
    try:
        try:
            winreg.DeleteValue(key, name)
            deleted = True
        except FileNotFoundError:
            deleted = False
    finally:
        winreg.CloseKey(key)

    if deleted:
        ctypes.windll.kernel32.SetEnvironmentVariableW(name, None)
        _broadcast_setting_change()

    return deleted


def _broadcast_setting_change() -> None:
    """Best-effort WM_SETTINGCHANGE broadcast (non-fatal on failure)."""
    if SYSTEM != "Windows":
        return
    try:
        ps_script = (
            "Add-Type -Namespace Win32 -Name User32 -MemberDefinition @'"
            "[System.Runtime.InteropServices.DllImport(\"user32.dll\","
            " SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]"
            "public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg,"
            " IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);'"
            "@\n"
            "$HWND_BROADCAST = [IntPtr]::Zero\n"
            "$WM_SETTINGCHANGE = 0x001A\n"
            "$result = [IntPtr]::Zero\n"
            "[Win32.User32]::SendMessageTimeout($HWND_BROADCAST,"
            " $WM_SETTINGCHANGE, [IntPtr]::Zero, \"Environment\", 2, 1000,"
            " [ref]$result) | Out-Null\n"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


# ============================================================
# macOS / Linux stubs (v0.1 read-only)
# ============================================================

def _unix_read_all_user_env() -> Dict[str, str]:
    return dict(os.environ)


def _unix_set_user_env(name: str, value: str) -> None:
    raise NotImplementedError(
        f"Setting env vars on {SYSTEM} is not supported in v0.1. "
        "Edit your shell rc file directly."
    )


def _unix_delete_user_env(name: str) -> bool:
    raise NotImplementedError(
        f"Deleting env vars on {SYSTEM} is not supported in v0.1."
    )


# ============================================================
# Public env var API
# ============================================================

def read_all_user_env() -> Dict[str, str]:
    """Read all User-level env vars (raw, unfiltered)."""
    if SYSTEM == "Windows":
        return _windows_read_all_user_env()
    return _unix_read_all_user_env()


def read_managed_env() -> Dict[str, str]:
    """
    Read env vars but ONLY return those in the managed whitelist.

    This is what the panel's "Managed" view shows. By design, system vars
    (PATH, OneDrive, etc.) and unmanaged vars are invisible here — even if
    they exist in the registry.
    """
    all_env = read_all_user_env()
    managed = get_managed_keys()
    return {k: v for k, v in all_env.items() if k in managed}


def set_user_env(name: str, value: str) -> None:
    """
    Set a User-level env var.

    For backward compatibility, if the key is NOT already in the whitelist,
    it's auto-added (with empty binding). Callers that want to set a binding
    at create time should call set_user_env() then add_managed_key() with the
    binding fields — or use the higher-level create_key flow in main.py.
    """
    _validate_name(name)
    if value is None:
        raise ValueError("value cannot be None")

    if SYSTEM == "Windows":
        _windows_set_user_env(name, value)
    else:
        _unix_set_user_env(name, value)

    # Auto-add to managed whitelist if not present (legacy behavior — caller
    # can refine binding via add_managed_key() / update_binding() after).
    if name not in get_managed_keys():
        add_managed_key(name)


def delete_user_env(name: str) -> bool:
    """
    Delete a User-level env var AND remove from managed whitelist.
    """
    _validate_name(name)
    if SYSTEM == "Windows":
        deleted = _windows_delete_user_env(name)
    else:
        deleted = _unix_delete_user_env(name)

    if deleted:
        remove_managed_key(name)
    return deleted


def _validate_name(name: str) -> None:
    if not name:
        raise ValueError("Environment variable name cannot be empty")
    if not isinstance(name, str):
        raise ValueError("Environment variable name must be a string")
    if not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
        raise ValueError(
            f"Invalid env var name '{name}'. "
            "Use only letters, digits, and underscores."
        )
    reserved = {"PATH", "PATHEXT", "OS", "PROCESSOR_ARCHITECTURE",
                "SYSTEMROOT", "WINDIR", "PROGRAMDATA"}
    if name in reserved:
        raise ValueError(
            f"'{name}' is a reserved Windows variable. "
            "Modifying it could break your system. Aborting."
        )


# ============================================================
# LLM-key classifier (imported from classifier.py for clarity)
# ============================================================

try:
    from classifier import classify as _classify
except ImportError:
    # Fallback — should not happen in normal operation
    def _classify(name, value):
        return {"confidence": "low", "reasons": ["classifier unavailable"], "auto_adopt": False, "score": 0}


def discover_llm_keys() -> List[Dict]:
    """
    Scan ALL user env vars and return those that look like LLM keys.

    Each result includes:
        - name, value, masked_value
        - confidence: high | medium | low | excluded
        - reasons: list of human-readable explanations
        - auto_adopt: True if confident enough to suggest one-click adoption
        - is_managed: True if already in whitelist
        - in_env: True if the env var actually exists

    Three-section result for the Discover view:
        - adoptable: high confidence, not yet managed
        - review: medium confidence OR high but already managed
        - skipped: low / excluded (not LLM)
    """
    all_env = read_all_user_env()
    managed = get_managed_keys()

    adoptable: List[Dict] = []
    review: List[Dict] = []
    skipped: List[Dict] = []

    for name, value in sorted(all_env.items()):
        result = _classify(name, value)
        entry = {
            "name": name,
            "value_preview": (value[:4] + "****" + value[-4:]) if len(value) > 8 else "****",
            "length": len(value),
            "confidence": result["confidence"],
            "reasons": result["reasons"],
            "auto_adopt": result["auto_adopt"],
            "score": result["score"],
            "is_managed": name in managed,
        }

        if result["confidence"] == "excluded" or result["confidence"] == "low":
            skipped.append(entry)
        elif result["auto_adopt"] and not entry["is_managed"]:
            adoptable.append(entry)
        else:
            review.append(entry)

    return {
        "adoptable": adoptable,
        "review": review,
        "skipped_count": len(skipped),  # Don't return skipped entries by default — could be many
        "total_scanned": len(all_env),
    }


def adopt_key(name: str, provider: str = "", base_url: str = "", default_model: str = "") -> bool:
    """
    Add `name` to the managed whitelist with optional provider binding.

    The env var must already exist. If binding fields are provided, they're
    persisted with the key. Returns True if newly adopted, False if already managed.
    """
    all_env = read_all_user_env()
    if name not in all_env:
        raise ValueError(f"Cannot adopt '{name}': env var does not exist")
    if name in get_managed_keys():
        # Already managed — update binding if caller provided one
        if base_url:
            update_binding(name, provider, base_url, default_model)
        return False
    add_managed_key(name, provider=provider, base_url=base_url, default_model=default_model)
    return True


def unadopt_key(name: str) -> bool:
    """
    Remove `name` from the managed whitelist. Does NOT delete the env var.
    """
    if name not in get_managed_keys():
        return False
    remove_managed_key(name)
    return True


def adopt_keys_bulk(items: List[Dict[str, str]]) -> Dict:
    """
    Adopt multiple keys at once, each with its own optional binding.

    Args:
        items: list of dicts, each with at least {"name": ...}, and optionally
               {"provider": ..., "base_url": ..., "default_model": ...}

    Returns counts of success/failure.
    """
    all_env = read_all_user_env()
    managed = get_managed_keys()
    adopted = []
    skipped = []

    for item in items:
        name = item.get("name", "").strip() if isinstance(item, dict) else ""
        if not name:
            skipped.append({"name": "", "reason": "missing name"})
            continue
        if name not in all_env:
            skipped.append({"name": name, "reason": "env var does not exist"})
        elif name in managed:
            skipped.append({"name": name, "reason": "already managed"})
        else:
            add_managed_key(
                name,
                provider=item.get("provider", ""),
                base_url=item.get("base_url", ""),
                default_model=item.get("default_model", ""),
            )
            adopted.append(name)

    return {
        "adopted": adopted,
        "skipped": skipped,
        "adopted_count": len(adopted),
        "skipped_count": len(skipped),
    }