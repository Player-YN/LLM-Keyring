# 🔑 LLM-Keyring

> **A local panel that turns LLM API keys into OS environment variables — no CLI, no cloud, no leak risk.**

LLM-Keyring is a tiny browser-based panel that runs on your machine and lets
you add, view, edit, and delete User-level environment variables through a
clean GUI. Built for AI developers who keep switching between OpenAI,
Anthropic, Hugging Face, DeepSeek, 硅基流动, 火山方舟, and a dozen other
providers — and are tired of `setx` every single time.

![LLM-Keyring Panel](docs/screenshot.png)

---

## ✨ Features

- **One-click CRUD** for any User-level environment variable
- **24 preset templates** across 3 categories — International, Aggregator, Chinese
- **Live search** by name
- **Whitelist-based "Managed" view** — only keys you opt-in appear (PATH, OneDrive, etc. are invisible by design)
- **"Discover" view** — auto-classifies your existing env vars and surfaces probable LLM keys for one-click adoption
- **Built-in Chat tab** — test any managed key against a real model, with capability matrix and streaming responses
- **Import / Export `.env`** for Docker, Linux servers, CI/CD
- **Sensitive masking** — values show as `sk-p****xyz`, click 👁 to reveal
- **Copy-to-clipboard** with one click
- **Dark mode** with system preference detection
- **EN / ZH i18n** with auto-detect
- **Zero cloud, zero account, zero telemetry** — your keys never leave your machine
- **Single-file `.exe`** available (no Python install required)

---

## 🚀 Quick Start (Windows)

### Option A: From source (you have Python 3.9+)

```powershell
git clone https://github.com/Player-YN/LLM-Keyring.git
cd LLM-Keyring
.\start.bat
```

Your default browser opens to `http://localhost:8765`. That's it.

### Option B: Use the `.exe` (no Python needed)

Download `llm-keyring.exe` from the [Releases](../../releases) page, double-click it.
Your browser opens automatically.

> **First time?** Run `pip install -r requirements.txt` (Option A) — `start.bat`
> will do this for you automatically.

---

## 🖥️ Usage

### Add a key

1. Click **+ Add Key** (top right) **or** pick a template from the sidebar.
2. Type the name (e.g. `OPENAI_API_KEY`) and paste your key value.
3. Click **Add**.

The key is written to `HKCU\Environment`. **Open a new** PowerShell / CMD
window and run:

```powershell
echo $env:OPENAI_API_KEY
```

You should see your key.

### Use it in Python / DSPy

```python
import os
import dspy

# DSPy auto-reads OPENAI_API_KEY from os.environ
lm = dspy.LM("openai/gpt-4o-mini")
dspy.configure(lm=lm)
```

No code changes needed. Your existing scripts just work.

### Import a `.env` file

1. Click **Import** in the header.
2. Paste the contents of your `.env` file.
3. Click **Import**.

Each `KEY=VALUE` line becomes a User env var. Invalid lines (no `=`) are
skipped with a count shown.

### Export to `.env`

Click **Export** in the header. A `.env` file downloads — ready for Docker,
Linux servers, or CI/CD pipelines.

---

## 🧩 Supported Providers (24 presets)

**International (10)**
OpenAI · Anthropic (Claude) · Google Gemini · Mistral · Cohere · Groq · Perplexity · xAI (Grok) · DeepSeek · Moonshot (Kimi)

**Aggregator (9)**
OpenRouter · Together AI · Fireworks · Replicate · Hugging Face · Vertex AI (Claude) · Azure OpenAI · AWS Bedrock · Anyscale

**Chinese (5)**
硅基流动 (SiliconFlow) · 火山方舟 (Ark) / Coding Plan · 智谱 BigModel · 百度千帆 · 阿里 DashScope (通义千问)

Missing one? You can add any custom name — pick "Add Key" and type your own.

---

## 🛠️ Troubleshooting

### "I added a key, but my already-open terminal doesn't see it."

**Already-running processes won't reload env vars** — that's a Windows
kernel limitation, not a bug. The env block is copied into a process at
startup and stays frozen.

LLM-Keyring uses a **triple-write strategy** to minimize this:

1. Writes to `HKCU\Environment` (persists across reboots)
2. Calls `SetEnvironmentVariableW` (updates the kernel session env block,
   so any process started *after* this sees the new var)
3. Broadcasts `WM_SETTINGCHANGE` (notifies GUI apps like Explorer)

So if you open a **new** PowerShell or CMD window after adding a key, it
will see the var. Already-open windows won't, until you restart them.

### "Why not use `setx` directly?"

`setx` works but has quirks:
- Truncates values at 1024 characters
- Strips quotes inconsistently
- Requires PATH lookup or shell escaping

LLM-Keyring writes directly to `HKCU\Environment` via `winreg`, which
handles long values, special characters, and PEM keys reliably. We still
broadcast `WM_SETTINGCHANGE` so apps that listen (Explorer, some IDEs) see
the change immediately.

### "Why not use HashiCorp Vault / Infisical / Doppler?"

Vault and friends are designed for **teams**: secret rotation, audit logs,
RBAC, compliance reporting. They're overkill (and slow + complex) for a
solo developer managing 5–10 API keys.

Use them if you have a team. Use LLM-Keyring if you're a developer who
just wants to stop typing `setx` every day.

### "Will this leak my keys to the internet?"

**No.** The backend binds to `127.0.0.1` only — it's not reachable from
your network. The frontend is a static HTML file served from the same
process. No external calls, no telemetry, no analytics.

### "Why is the panel showing `PATH` and other system vars?"

LLM-Keyring shows ALL User-level env vars (not just API keys), because you
might want to edit any of them. We do block edits to reserved names
(`PATH`, `PATHEXT`, `OS`, etc.) to prevent breaking your system.

---

## 🧪 Platform Support

| Platform | Status | Notes |
|---|---|---|
| **Windows 10 / 11** | ✅ Full | Registry-based read/write |
| **macOS** | ⚠️ Read-only | Read from `os.environ` only; write raises NotImplementedError |
| **Linux** | ⚠️ Read-only | Same as macOS |

Windows is the primary target. macOS / Linux support is best-effort in v0.1.

---

## 📦 Building the `.exe` Yourself

```powershell
pip install -r requirements-build.txt
pyinstaller --onefile --name llm-keyring --add-data "frontend;frontend" main.py
```

The binary appears at `dist/llm-keyring.exe`. Run it directly — no Python
needed on the target machine.

> **Note:** `--onefile` packages take ~10–20 seconds to start (they extract
> to a temp directory). For a faster startup, use `--onedir` instead.

---

## 🗺️ Roadmap

- [ ] macOS full support (parse `~/.MacOSX/environment.plist`)
- [ ] Linux full support (parse `~/.pam_environment`)
- [ ] Encrypted local backup (export to `.keyring.json` with passphrase)
- [ ] Multi-profile switching (e.g., "Work" vs "Personal")
- [ ] Tauri version (smaller binary, native feel)
- [ ] Group/tag keys (e.g., "Production", "Test", "Personal")
- [ ] Auto-start on boot (Windows Task Scheduler integration)
- [ ] Power-user CLI mode (`llm-keyring list`, `llm-keyring set KEY=val`)

---

## 🤝 Contributing

PRs welcome. Keep it simple. This is a 200-line project on purpose.

- Don't add features outside the Roadmap above without discussion
- Don't add cloud / network dependencies
- Don't add telemetry
- Test on Windows before submitting

---

## 📄 License

[MIT](LICENSE) — use it, fork it, sell it, whatever. Just keep the
copyright notice.

---

## 🙏 Acknowledgements

Built with [FastAPI](https://fastapi.tiangolo.com/),
[TailwindCSS](https://tailwindcss.com/), and
[Alpine.js](https://alpinejs.dev/).

Inspired by the daily pain of typing `setx` for the 47th time.