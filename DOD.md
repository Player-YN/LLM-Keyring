# LLM-Keyring — Definition of Done (V0.FINAL)

> 状态: **FINAL** (用户已批准，开始执行)
> 用户原话："按这个开干，但是你帮我推送github，我会登录，你来操作"
> 任务类型: code feature (FastAPI + 单页前端) + repo artifact (开源) + packaging (PyInstaller .exe)
> 下游执行者: Mavis (本次会话内自执行)
> 存储路径: `C:\Users\yyy\.mavis\sessions\mvs_a3583d6b83ac48d8bc81b15b6b9bbd77\workspace\llm-keyring\DOD.md`
> 最后更新: 2026-06-27

---

## 1. Scope

### 1.1 Goal / Why

**LLM-Keyring 是一个本地运行的轻量 Web 面板**，让 AI 开发者通过浏览器图形界面管理 LLM API Key（操作系统级环境变量），替代反复的 `setx` 命令行操作，并以 MIT 协议开源到 GitHub。

**用户视角的成功标准**：双击 `start.bat` → 浏览器自动打开 → 在面板里点几下添加一个 key → 打开新的 PowerShell 跑 Python，`os.environ` 立刻能读到。**整个流程 < 30 秒、不碰命令行**。

### 1.2 In Scope (v0.1)

**核心功能**
- ✅ 任意环境变量的 **CRUD**：添加 / 查看（脱敏）/ 删除
- ✅ **自定义名称 + 自定义值**（不限定 API key，通用环境变量）
- ✅ **25+ 预设模板**，3 大类：
  - **国际云厂商（10）**：OpenAI, Anthropic, Google Gemini, Mistral, Cohere, Groq, Perplexity, xAI (Grok), DeepSeek, Moonshot
  - **聚合器/路由（9）**：OpenRouter, Together, Fireworks, Replicate, HF, Vertex Claude, Azure OpenAI, AWS Bedrock, Anyscale
  - **国内聚合器（5）**：硅基流动 SiliconFlow, 火山方舟 Ark, 智谱 BigModel, 百度千帆, 阿里 DashScope
- ✅ **模板搜索**（input 框实时过滤，按 name 或 provider 匹配）
- ✅ **敏感值脱敏**（列表显示：前 4 字符 + `****` + 后 4 字符）
- ✅ **一键复制**（每行 key 旁边一个复制按钮）
- ✅ **导入 .env**（粘贴或拖拽 → 解析每行 `KEY=VALUE` → 创建环境变量）
- ✅ **导出 .env**（生成 `.env` 文件，标注 "For Docker / Linux / CI"）

**工程化**
- ✅ 跨平台代码骨架（Windows 完整实现 + macOS stub + start.sh 占位）
- ✅ PyInstaller 打包成单文件 `.exe`（目标用户不需要装 Python）
- ✅ Git init + MIT LICENSE + `.gitignore` + README

### 1.3 Out of Scope (v0.1)

> **划清边界 = 防止 scope creep**

- ❌ 云同步 / 账号系统 / 登录（单人本地工具）
- ❌ 团队共享（README 明确指向 Vault / LiteLLM Proxy）
- ❌ 加密存储（Windows 凭据管理器有自己的加密流程，但不易读入 env vars）
- ❌ 运行时注入到**已运行进程**（Windows console 不主动监听 env 变化，技术不可靠）
- ❌ 开机自启
- ❌ 多 profile 切换
- ❌ Linux 完整支持（README roadmap 里提一句即可）
- ❌ macOS 完整 UI 适配（start.sh + env_manager 占位，不做完整测试）
- ❌ 代码签名 / 苹果公证（v0.1 不需要）

### 1.4 Constraints & Assumptions

**硬约束**
- Python 3.9+（后端运行时）
- 后端仅绑定 `127.0.0.1:8765`（localhost，不暴露网络）
- 只写 Windows User 级环境变量（`HKCU\Environment`），不动 System 级（不需要管理员）
- MIT License
- 前端由 FastAPI 静态托管（避免 CORS 复杂度）

**[ASSUMPTION — 请确认]**
- README 写**英文**（面向国际开源社区；如果要 EN+中文双语，告诉我）
- v0.1 必须包含 `.exe` 打包（否则不算可发布）
- 项目名严格用 `LLM-Keyring`（首字母大写 + 横线），不是 `llm-keyring` 或 `LLM_Keyring`
- GitHub repo 创建由**你手动**完成（我不持有你的 GitHub 凭据），我只负责本地 git init + 给你 `gh repo create` 命令
- 后端用 `setx` 命令 + 直接读注册表两种方式实现（`setx` 走 PATH 触发广播，写注册表作为兜底）
- 端口 8765 冲突时自动选下一个可用端口（8766、8767...）

---

## 2. Acceptance Criteria

> 格式：Given-When-Then。覆盖 happy / edge / failure 三类，共 12 条。

### AC-1: Happy path — 添加自定义 key
**GIVEN** 面板运行在 `http://localhost:8765`，系统中不存在 `MY_TEST_KEY` 环境变量
**WHEN** 用户在 name 输入框填 `MY_TEST_KEY`，value 输入框填 `sk-test-1234`，点击 "Add"
**THEN** 列表新增一项，显示为 `sk-t****1234`（脱敏），**且** 此后新打开的 PowerShell 中 `$env:MY_TEST_KEY` 等于 `sk-test-1234`

### AC-2: Happy path — 应用预设模板
**GIVEN** 面板运行中，系统中不存在 `OPENAI_API_KEY`
**WHEN** 用户在模板搜索框输入 `openai`，从下拉中选择 "OPENAI_API_KEY (OpenAI)"，点击 "Use template"
**THEN** name 字段自动填入 `OPENAI_API_KEY`，用户只需手动填 value

### AC-3: Happy path — 删除 key
**GIVEN** `MY_TEST_KEY` 已存在并在面板列表中
**WHEN** 用户点击该行删除图标，确认删除
**THEN** 该行从列表消失，**且** 此后新打开的 PowerShell 中 `$env:MY_TEST_KEY` 为空

### AC-4: Edge case — 重复 key
**GIVEN** `OPENAI_API_KEY` 已存在，值为 `sk-old`
**WHEN** 用户尝试再添加一个 `OPENAI_API_KEY`，value 为 `sk-new`
**THEN** 面板弹出 "Key 已存在，是否覆盖？" 对话框；用户点确认后值更新为 `sk-new`；点取消则不修改

### AC-5: Edge case — 空输入
**GIVEN** 用户点击 "Add" 时 name 或 value 为空
**WHEN** 提交动作触发
**THEN** 面板内联报错 "Name required" 或 "Value required"，**不**发 API 请求，**不**创建环境变量

### AC-6: Edge case — 端口被占用
**GIVEN** 端口 8765 已被其他进程占用
**WHEN** 用户运行 `start.bat`
**THEN** 后端自动选下一个可用端口（8766、8767...），在终端打印实际 URL，浏览器自动打开正确 URL

### AC-7: Edge case — value 含特殊字符
**GIVEN** 用户粘贴的 value 包含引号、等号、换行符（PEM 密钥场景）
**WHEN** 用户点击 "Add"
**THEN** 值被正确存储，新 PowerShell 中读取完整无截断、无转义错误

### AC-8: Edge case — 搜索过滤
**GIVEN** 模板下拉框有 24 项
**WHEN** 用户在搜索框输入 `硅基`
**THEN** 仅 "SILICONFLOW_API_KEY (硅基流动)" 一项可见；清空搜索框后所有 24 项恢复

### AC-9: Edge case — .env 导入
**GIVEN** 用户粘贴了一段 5 行的 .env 内容（含 1 行无效格式）
**WHEN** 用户点击 "Import"
**THEN** 创建 4 个环境变量，1 个无效行被跳过并在面板提示 "Skipped 1 invalid line"

### AC-10: Failure mode — Python 未安装
**GIVEN** `python` 不在 PATH 中
**WHEN** 用户双击 `start.bat`
**THEN** 脚本打印清晰错误 "Python 3.9+ required. Install from python.org"，并附链接；退出码 = 1；不静默崩溃

### AC-11: Failure mode — 环境变量写入失败
**GIVEN** 后端 `setx` 调用返回非零（权限被拒等）
**WHEN** 用户点击 "Add"
**THEN** 面板显示错误 toast "Failed to set env var: <原因>"，环境变量未修改，无半状态残留

### AC-12: Failure mode — .env 导出到只读目录
**GIVEN** 用户点击 "Export .env"，当前工作目录只读
**WHEN** 后端尝试写文件
**THEN** 面板显示错误 "Cannot write .env to <path>: <原因>"，建议用户选择其他路径

---

## 3. Definition of Done (generic checklist)

### DoD-1: 功能完整性
- [ ] 12 条 AC 全部手动验证通过（v0.1 不要求自动化测试套件）
- [ ] 后端 Windows User env var 写入走 `setx` + 注册表兜底
- [ ] 前端在 Chrome / Edge 中加载，console 无 error
- [ ] 搜索框实时过滤无卡顿

### DoD-2: 跨平台就绪
- [ ] `env_manager.py` 用 `sys.platform` 探测平台，分 Windows / macOS 实现
- [ ] Windows 路径完整测试；macOS 代码存在但可 `raise NotImplementedError`，不崩
- [ ] `start.sh` 存在并包含 TODO 注释（macOS 用户能看见 "未完成"）

### DoD-3: 打包
- [ ] `pyinstaller --onefile backend/main.py` 产出 `dist/llm-keyring.exe`
- [ ] .exe 在一台干净的 Windows VM（无 Python）上能正常运行
- [ ] .exe 文件大小 < 50 MB

### DoD-4: 仓库卫生
- [ ] `git init` 完成，`.gitignore` 排除 `__pycache__`、`dist/`、`build/`、`.env`、`*.spec`
- [ ] `LICENSE`（MIT）位于仓库根目录
- [ ] `README.md` 包含：项目描述、截图、安装步骤、使用截图或动图、FAQ（为什么不用 Vault？）、Roadmap
- [ ] 首次 commit 包含全部源文件，commit message 有意义

### DoD-5: 文档
- [ ] `env_manager.py` 公共函数有 docstring
- [ ] README 有 troubleshooting 章节，专门解释 "为什么我新加的 key 在已打开的终端里看不到"（因为已运行进程不重读 env）
- [ ] README 至少 1 张面板截图

### DoD-6: 安全性
- [ ] 任何源文件中无明文密钥（key 只能由用户输入）
- [ ] 后端绑定 `127.0.0.1`，不绑 `0.0.0.0`
- [ ] 无任何遥测 / 分析 / 远程调用

### DoD-7: 手动冒烟测试（交付前必做）
- [ ] 添加一个测试 key → 新 PowerShell 验证 → 删除 → 验证消失
- [ ] 搜索模板 → 应用 → 填 value → 保存
- [ ] 导出 .env → 打开文件 → 验证内容格式
- [ ] 导入 .env → 在列表中看到所有 key
- [ ] **重启面板 → 之前添加的 key 仍然在列表中**（证明 env var 已持久化，不是只存内存）

---

## 4. Agent Execution Hints

- **角色**：全栈开发者 + 开源仓库维护者
- **工具**：write / edit / bash / read 写代码；web_search / webfetch 仅在查文档时用；不需要 MCP 媒体工具
- **输入**：本 DoD + 你之前几轮对话中确立的上下文
- **输出格式**：
  - 代码在 `backend/*.py` 和 `frontend/index.html`
  - `start.bat`、`start.sh`、`requirements.txt`、`.gitignore`、`LICENSE`、`README.md`
  - 符合 conventional commit 规范的 git commit
  - 最终给一段总结，列出所有创建的文件
- **推理风格**：架构上一步一步想清楚（env var 写入策略：setx vs 注册表 vs `os.environ`），但不 over-engineer；能用 30 行解决的别写 100 行
- **停止条件**（满足全部才算完成）：
  - 12 条 AC 全部手动验证通过 **且**
  - .exe 打包完成并能运行 **且**
  - Git 初始化 + 首次 commit **且**
  - README 完整带截图
- **失败行为**：
  - PyInstaller 打包失败：在 Open Questions 中记录失败原因，**不**静默跳过（v0.1 必须有 .exe）
  - 你电脑 `setx` 不可用：fallback 到直接写注册表 `winreg`，并在代码中标注
  - 用户对任何 AC 提出反对：暂停开发，先问清楚再继续

---

## 5. DoR Self-Check

> 全绿 = DoD 可执行。任何红项都是阻塞。

- [x] Goal 清晰，"双击 start.bat → 30 秒内加 key" 已是可观察的成功标准
- [x] In-Scope / Out-of-Scope 明确，无模糊地带
- [x] 12 条 AC：happy / edge / failure 三类齐全
- [x] 所有 AC 严格 Given-When-Then
- [x] DoD checklist 已按 code feature + repo artifact 裁剪
- [x] 所有 [ASSUMPTION] 标记已被用户确认或修正（采用默认假设：英文 README、用户手动登录后由我推送 GitHub、Tailwind 极简风）
- [x] 失败行为有明确定义（AC-10 / AC-11 / AC-12）
- [x] 存储路径明确（`workspace/llm-keyring/`）
- [x] README 语言确认（英文）
- [x] 你口头/书面确认 DoD 进入 FINAL 状态（"按这个开干"）

---

## 6. Open Questions

> 用户已决定：以下问题按默认假设推进，不阻塞开发。

- **OQ-1**：README 语言 — **仅英文**（开源面向国际社区）
- **OQ-2**：GitHub repo 创建 — **用户自己登录后由我操作**（用户原话）
- **OQ-3**：视觉风格 — **Tailwind 极简风 + 暗色模式**（专业感）
- **OQ-4**：图标 — **用 emoji 占位**，未来可换 SVG
- **OQ-5**：代码签名 — **不做**，README 不提

---

## 7. Changelog

- **V0.1 (2026-06-27)**：初稿。基于前几轮对话确认的 6 个决策点。
- **V0.FINAL (2026-06-27)**：用户确认 "按这个开干，但是帮我推送github"。开始执行。