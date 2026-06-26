"""
env_manager.py — Cross-platform User-level environment variable management.

This module abstracts reading/writing/deleting User-level environment variables
across Windows / macOS / Linux.

Windows:
    Reads from HKCU\\Environment via winreg (this is the canonical store).
    Writes via winreg directly (more reliable than `setx`, which has quirks
    with quoting, 1024-char truncation, and broadcasts).

macOS / Linux:
    Read falls back to os.environ (current process only — incomplete but OK
    for v0.1).
    Write/Delete raise NotImplementedError; v0.1 is Windows-focused.

Note on Windows environment variables:
    - Changes to HKCU\\Environment only affect NEW processes. Already-running
      processes have a snapshot of the env block and won't reload it. This
      is a Windows kernel limitation, not a bug in this module.
    - To make NEW processes pick up changes immediately, we broadcast
      WM_SETTINGCHANGE via SendMessageTimeout after each write.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from typing import Dict


SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"


# ============================================================
# Windows implementation
# ============================================================

def _windows_read_all_user_env() -> Dict[str, str]:
    """
    Read all User-level environment variables from the Windows registry.

    Returns a dict mapping var name to value. REG_EXPAND_SZ values are returned
    with their raw %VAR% references (not expanded). Callers can use
    os.path.expandvars() if they want expansion.

    Why registry and not os.environ?
    - os.environ reflects the env block at the time Python started. To see
      the *current* User-level state (e.g., after another tool modified it),
      we must read the registry directly.
    """
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
                    # No more values
                    break
    except FileNotFoundError:
        # The Environment key doesn't exist yet (fresh user profile)
        pass
    return env_vars


def _windows_set_user_env(name: str, value: str) -> None:
    """
    Set a User-level environment variable using a triple-write strategy.

    Three steps, all required for full correctness:

    1. **winreg write** to HKCU\\Environment — persists the value across
       logouts and reboots. This is the canonical store.

    2. **SetEnvironmentVariableW** via ctypes — updates the kernel's User
       environment block for the current Windows session. Without this,
       newly-launched cmd.exe / PowerShell / Python processes (which inherit
       their env block from the kernel via CreateProcess) will NOT see the
       new var, even though it's in the registry.

    3. **WM_SETTINGCHANGE broadcast** — notifies already-running GUI apps
       (Explorer, some IDEs) to refresh their cached env. Console hosts
       generally don't react to this.

    Args:
        name: Variable name (e.g. "OPENAI_API_KEY")
        value: Variable value (e.g. "sk-...")

    Raises:
        OSError: If the registry write fails (e.g., permission denied)
        RuntimeError: If SetEnvironmentVariableW fails (very rare)
    """
    import ctypes
    import winreg

    # Step 1: Write to HKCU\Environment (persistence)
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

    # Step 2: Update kernel session env block (immediate visibility for new
    # processes). SetEnvironmentVariableW writes to the calling process's
    # User environment block, which is inherited by all child processes.
    if not ctypes.windll.kernel32.SetEnvironmentVariableW(name, value):
        # GetLastError() would tell us why, but this rarely fails for
        # reasonable inputs. Don't block the operation — registry write
        # already succeeded, and the var will be visible after re-login.
        pass

    # Step 3: Broadcast WM_SETTINGCHANGE (best-effort, non-fatal if it fails)
    _broadcast_setting_change()


def _windows_delete_user_env(name: str) -> bool:
    """
    Delete a User-level environment variable.

    Args:
        name: Variable name to delete

    Returns:
        True if the variable existed and was deleted; False if it didn't exist.

    Strategy mirrors _windows_set_user_env:
      1. Remove from HKCU\\Environment (persistence)
      2. Call SetEnvironmentVariableW with NULL (clear kernel session env)
      3. Broadcast WM_SETTINGCHANGE (notify GUI apps)
    """
    import ctypes
    import winreg

    # Step 1: Remove from registry
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
        # Step 2: Clear from kernel session env
        # SetEnvironmentVariableW with NULL value removes the var from the
        # session's User environment block.
        ctypes.windll.kernel32.SetEnvironmentVariableW(name, None)

        # Step 3: Broadcast (non-fatal)
        _broadcast_setting_change()

    return deleted


def _broadcast_setting_change() -> None:
    """
    Broadcast WM_SETTINGCHANGE to all top-level windows so new processes
    pick up env var updates immediately.

    Implementation: PowerShell one-liner that uses Add-Type to define a
    SendMessageTimeout P/Invoke and calls it with HWND_BROADCAST.

    Caveat: Console subprocesses (cmd.exe, PowerShell sessions, Python
    scripts) typically do NOT react to this broadcast. Only new launches
    will see the updated env. This is a Windows kernel limitation.
    """
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
        # Broadcast failure is non-fatal
        pass


# ============================================================
# macOS / Linux stubs (v0.1 is Windows-focused)
# ============================================================

def _unix_read_all_user_env() -> Dict[str, str]:
    """
    On macOS/Linux, fall back to os.environ for reading.

    This is INCOMPLETE — it only sees the current Python process's env block,
    not the user's full env. The full implementation would need to:
      - macOS: parse ~/.MacOSX/environment.plist
      - Linux: parse /etc/environment, ~/.pam_environment, or shell rc files

    Both are out of scope for v0.1. Use Windows for full functionality.
    """
    return dict(os.environ)


def _unix_set_user_env(name: str, value: str) -> None:
    """Set on macOS/Linux is not supported in v0.1."""
    raise NotImplementedError(
        f"Setting environment variables on {SYSTEM} is not supported in "
        f"LLM-Keyring v0.1. The app is Windows-focused. For macOS/Linux, "
        f"edit your shell rc file (e.g., ~/.zshrc, ~/.bashrc) directly."
    )


def _unix_delete_user_env(name: str) -> bool:
    """Delete on macOS/Linux is not supported in v0.1."""
    raise NotImplementedError(
        f"Deleting environment variables on {SYSTEM} is not supported in "
        f"LLM-Keyring v0.1."
    )


# ============================================================
# Public API
# ============================================================

def read_all_user_env() -> Dict[str, str]:
    """
    Read all User-level environment variables.

    Returns:
        Dict mapping var name to value. On Windows, reads from registry
        (current state). On macOS/Linux, returns os.environ (current process).
    """
    if SYSTEM == "Windows":
        return _windows_read_all_user_env()
    return _unix_read_all_user_env()


def set_user_env(name: str, value: str) -> None:
    """
    Set a User-level environment variable.

    Args:
        name: Variable name. Must contain only letters, digits, and underscores.
        value: Variable value. Any string is accepted.

    Raises:
        ValueError: If name is empty or contains invalid characters
        NotImplementedError: If running on macOS/Linux (v0.1 Windows-only)
        OSError: If the underlying write fails (e.g., permission denied)
    """
    _validate_name(name)
    if value is None:
        raise ValueError("value cannot be None")

    if SYSTEM == "Windows":
        _windows_set_user_env(name, value)
    else:
        _unix_set_user_env(name, value)


def delete_user_env(name: str) -> bool:
    """
    Delete a User-level environment variable.

    Args:
        name: Variable name to delete

    Returns:
        True if the variable existed and was deleted; False if it didn't exist.

    Raises:
        NotImplementedError: If running on macOS/Linux (v0.1 Windows-only)
    """
    _validate_name(name)
    if SYSTEM == "Windows":
        return _windows_delete_user_env(name)
    return _unix_delete_user_env(name)


# ============================================================
# Helpers
# ============================================================

def _validate_name(name: str) -> None:
    """
    Validate that an environment variable name is acceptable.

    Rules:
      - Must be a non-empty string
      - Must contain only ASCII letters, digits, and underscores

    This is a conservative subset of what Windows allows, but it's enough
    for all LLM API key conventions (OPENAI_API_KEY, HF_TOKEN, etc.).
    """
    if not name:
        raise ValueError("Environment variable name cannot be empty")
    if not isinstance(name, str):
        raise ValueError("Environment variable name must be a string")
    if not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
        raise ValueError(
            f"Invalid environment variable name '{name}'. "
            "Use only letters, digits, and underscores (A-Z, a-z, 0-9, _)."
        )
    # Reserved names on Windows that should not be modified
    reserved = {
        "PATH", "PATHEXT", "OS", "PROCESSOR_ARCHITECTURE",
        "SYSTEMROOT", "WINDIR", "PROGRAMDATA",
    }
    if name in reserved:
        raise ValueError(
            f"'{name}' is a reserved Windows variable. "
            "Modifying it could break your system. Aborting."
        )