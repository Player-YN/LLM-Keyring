# 🔑 LLM-Keyring

> **本地浏览器面板，把 LLM API key 变成系统环境变量 — 无命令行、无云端、无泄露风险。**

LLM-Keyring 是一个运行在你电脑上的轻量浏览器面板，让你通过干净的图形界面**管理**、**发现**、**导入** LLM API key（作为 User 级环境变量）。为那些每天在 OpenAI、Anthropic、Hugging Face、DeepSeek、硅基流动、火山方舟 之间切换的 AI 开发者设计 — 再也不用反复敲 `setx`。

![LLM-Keyring Panel](docs/screenshot.png)

---

## ✨ 核心特性

- **双视图安全模型**：
  - **Managed（受管理的）**：只显示你明确标记为「这个 key 我要管」的，OneDrive / Office / 系统变量完全看不见
  - **Discover（自动发现）**：扫描你电脑里所有疑似 LLM 的 key，一键 Adopt 进 Managed
- **24 个预设模板** — International / Aggregator / Chinese 三类
- **实时搜索、复制到剪贴板、敏感值脱敏（`sk-p****xyz`）**
- **导入 / 导出 `.env`** — 给 Docker、Linux 服务器、CI/CD 用
- **中英双语切换** — 右上角一键切换
- **苹果风格 UI** — Inter 字体 + Lucide 图标 + 毛玻璃 + 微动效 + 暗色模式
- **零云端、零账号、零遥测** — key 从不离开你的电脑
- **单文件 `.exe`**（无需装 Python）

---

## 🚀 快速开始（Windows）

### 方式 A：从源码运行（需要 Python 3.9+）

```powershell
git clone https://github.com/Player-YN/LLM-Keyring.git
cd LLM-Keyring
.\start.bat
```

浏览器自动打开 `http://localhost:8765`。搞定。

### 方式 B：用 `.exe`（不需要 Python）

从 [Releases](../../releases) 下载 `llm-keyring.exe`，双击运行即可。

---

## 🖥️ 使用

### 添加一个 Key

1. 点击右上角 **+ Add Key**，或从右下角书签图标打开**预设模板**
2. 输入 name（例如 `OPENAI_API_KEY`）和 value（你的 key）
3. 点 **Add**

key 写入 Windows User 级环境变量后，**新打开**的 PowerShell 立即可见：

```powershell
echo $env:OPENAI_API_KEY
# 应该输出你的 key
```

### 在 Python / DSPy 中使用

```python
import os
import dspy

# DSPy 自动从 os.environ 读 OPENAI_API_KEY
lm = dspy.LM("openai/gpt-4o-mini")
dspy.configure(lm=lm)
```

你已有的脚本不用改任何东西。

### 🆕 发现电脑上已有的 Key

如果你之前手动 `setx` 过一些 key，或者其他工具帮你设置过：

1. 切到 **Discover** 标签（顶部）
2. 面板会自动扫描你电脑上的所有 User env var
3. **🟢 高置信度**（命名规范 + value 前缀匹配）一键 **Adopt**
4. **🟡 中置信度**（命名不规则但有点像）看一眼决定要不要 Adopt
5. **Adopt** 之后，key 进入 Managed，从此可以正常 CRUD

**没找到的 key？** Discover 底部有 **+ Add Manually**，手动加任意自定义名称。

### 导入 `.env`

1. 点击顶部 **Import** 按钮
2. 粘贴 `.env` 内容
3. 点 **Import** — 每行 `KEY=VALUE` 都会创建并加入白名单

### 导出 `.env`

点击顶部 **Download** 图标，下载当前 Managed 的 key 为 `.env` 文件 — 给 Docker、Linux 服务器、CI/CD 用。

---

## 🔒 安全模型

### 为什么默认看不到所有 env var？

LLM-Keyring 采用**白名单机制**：

- 第一次打开时，**Managed 视图是空的**
- 你必须主动 **Adopt**（发现模式下点按钮）或 **Add** 才能让某个 key 进入 Managed
- 没在白名单里的 key，**面板完全看不见** — 包括你的 OneDrive 路径、PATH、系统变量等

这样：
- ✅ **绝对安全**：OneDrive / Office / Azure AD / OAuth token 等都不会被误操作
- ✅ **不会误删**：你看不到的 key 删不掉
- ✅ **可追溯**：白名单存于 `%APPDATA%\LLM-Keyring\managed_keys.json`

### Discover 视图会扫描哪些？

Discover 扫描你 User 级所有 env var，然后用启发式规则分类：

| 分类 | 处理 |
|---|---|
| 🟢 **高置信度**（预设模板名 / `*_API_KEY` / `*_TOKEN` 等 + value 有 `sk-` `hf_` 等前缀） | 显示在 Discover，一键 Adopt |
| 🟡 **中置信度**（`*_KEY` / `*_SECRET` / 含 LLM 等关键词） | 显示但需要你确认 |
| ⚪ **低置信度** | 不显示（不打扰你） |
| ⚫ **黑名单**（`PATH`、`OneDrive`、`TEMP`、`MAGICK_*`、Azure AD、OAuth token 等） | **永远不显示** |

### 为什么不写注册表就够？

只写注册表的话，**新进程读不到**新的 env var。LLM-Keyring 使用**三写策略**：

1. **写注册表**（`HKCU\Environment`）— 持久化，重启后保留
2. **SetEnvironmentVariableW** — 更新内核会话 env 块，**新进程立刻可见**
3. **WM_SETTINGCHANGE 广播** — 通知 GUI 应用刷新

---

## 🌐 中英切换

- 右上角语言切换按钮
- 偏好保存在 `localStorage`
- 初次访问会自动检测浏览器语言

---

## 🧩 支持的提供商（24 个预设）

**International (10)**
OpenAI · Anthropic (Claude) · Google Gemini · Mistral · Cohere · Groq · Perplexity · xAI (Grok) · DeepSeek · Moonshot (Kimi)

**Aggregator (9)**
OpenRouter · Together AI · Fireworks · Replicate · Hugging Face · Vertex AI (Claude) · Azure OpenAI · AWS Bedrock · Anyscale

**Chinese (5)**
硅基流动 (SiliconFlow) · 火山方舟 (Ark) / Coding Plan · 智谱 BigModel · 百度千帆 · 阿里 DashScope (通义千问)

要加新的？直接在 **Add Manually** 输入任意名字。

---

## 🛠️ 故障排查

### 「我添加了 key，但已打开的终端里看不到」

**这是 Windows 内核限制，不是 bug。** 环境变量在进程启动时被复制到内存里，运行中不会重新加载。

LLM-Keyring 用**三写策略**把影响降到最小：
1. 写注册表 → 跨重启持久化
2. `SetEnvironmentVariableW` → 新启动的进程立刻看到
3. 广播 `WM_SETTINGCHANGE` → GUI 应用刷新

所以添加 key 后，**新开的 PowerShell / CMD** 能看到。已经开着的需要重启。

### 「为什么不直接用 `setx`？」

`setx` 各种坑：
- 1024 字符截断
- 引号处理不一致
- 需要 PATH 查找和 shell 转义

LLM-Keyring 直接写注册表（用 `winreg`）+ Win32 API，能正确处理长 value、特殊字符、PEM 密钥。

### 「为什么不用 HashiCorp Vault / Infisical？」

Vault 那套是给**团队**用的：密钥轮换、审计日志、RBAC、合规报告。个人开发者管 5-10 个 key 用它太重太慢。

有团队需求 → 用 Vault。
个人开发者 → 用 LLM-Keyring。

### 「会泄露我的 key 到互联网吗？」

**不会。**
- 后端只绑定 `127.0.0.1`
- 前端是 FastAPI 服务的静态 HTML
- 无外部调用、无遥测、无分析

---

## 🧪 平台支持

| 平台 | 状态 | 说明 |
|---|---|---|
| **Windows 10 / 11** | ✅ 完整支持 | 注册表读写 |
| **macOS** | ⚠️ 只读 | 从 `os.environ` 读，写入会抛 NotImplementedError |
| **Linux** | ⚠️ 只读 | 同 macOS |

Windows 是主要平台。macOS / Linux 是尽力而为。

---

## 📦 自己打包 `.exe`

```powershell
pip install -r requirements-build.txt
pyinstaller --onefile --name llm-keyring --add-data "frontend;frontend" main.py
```

产物在 `dist/llm-keyring.exe`。

> `--onefile` 启动慢（要解压到临时目录）。要快用 `--onedir`。

---

## 🗺️ Roadmap

- [ ] macOS 完整支持（解析 `~/.MacOSX/environment.plist`）
- [ ] Linux 完整支持（解析 `~/.pam_environment`）
- [ ] 加密本地备份（导出 `.keyring.json` + 密码）
- [ ] 多 profile 切换（"工作" / "个人"）
- [ ] Tauri 版本（更小的二进制 + 原生体验）
- [ ] 分组 / 标签（"生产" / "测试" / "个人"）
- [ ] 开机自启（Windows Task Scheduler 集成）
- [ ] CLI 模式（`llm-keyring list` / `set KEY=val`）
- [ ] macOS 完整 UI 适配

---

## 🤝 贡献

欢迎 PR。保持简单 — 这是个 200 行的项目，特意的。

- Roadmap 之外的功能先讨论
- 不加云端 / 网络依赖
- 不加遥测
- Windows 上测过再提 PR

---

## 📄 许可证

[MIT](LICENSE) — 用它、fork 它、卖它，啥都行。保留版权声明即可。

---

## 🙏 致谢

构建于 [FastAPI](https://fastapi.tiangolo.com/) ·
[TailwindCSS](https://tailwindcss.com/) ·
[Alpine.js](https://alpinejs.dev/) ·
[Lucide Icons](https://lucide.dev/) ·
[Inter Font](https://rsms.me/inter/)

灵感来自每天敲 47 次 `setx` 的痛苦。

---

## 英文 README

[English README](README.md) · [Issue Tracker](../../issues)