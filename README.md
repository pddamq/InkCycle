# Novel Agent · 小说创作 Agent

桌面级 AI 小说创作工具：从访谈开书、设定与大纲，到章节 **起草 → 审校 → 修订** 的 Agent 循环，支持整本后台创作、书籍导入与仿写、剧情流程图，以及可扩展的 **Skills** 与 **MCP** 工具。

| | |
| --- | --- |
| **前端** | Vue 3 · Vue Router · TDesign · Vite · pnpm |
| **后端** | Python · FastAPI · SQLite · OpenAI 兼容 API（SSE 流式） |
| **分发** | PyInstaller 单文件 EXE + pywebview 原生窗口（Windows） |

---

## 目录

- [特性](#特性)
- [快速开始（用户）](#快速开始用户)
- [从源码运行（开发者）](#从源码运行开发者)
- [测试](#测试)
- [打包 EXE](#打包-exe)
- [Agent 工具](#agent-工具)
- [Skills 与 MCP](#skills-与-mcp)
- [数据与隐私](#数据与隐私)
- [仓库结构](#仓库结构)
- [版本库与忽略规则](#版本库与忽略规则)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

---

## 特性

### 创作流程

- **开书访谈**：多轮盘问收集创作意图，生成可编辑的「创作蓝图」，并驱动后续向导。
- **创作向导**：按蓝图生成世界观、角色、卷章大纲。
- **章节 Agent 循环**：起草 → 自动审校（设定/角色/伏笔/时间线一致性）→ 修订，可多轮直至达标。
- **整本创作**：后台逐章写完一本书，进度持久化，关闭应用后可「继续创作」。
- **版本历史**：初稿/修订/手改/回滚均有记录，可预览、对比、回滚。

### 书籍管理与可视化

- 多项目书架（本地 SQLite）：进度、字数、伏笔一览。
- **导入书籍**：上传或粘贴 txt/md，自动拆章；解析文风；抽取角色、伏笔、时间线；**剧情流程图**（vue-flow）；支持**一键仿写**新书。
- 伏笔台账、时间线、审校报告（打分 + 分维度建议）。
- 导出 TXT / Markdown（整本 / 单卷 / 单章）。

### 扩展能力

- **Skills**：`SKILL.md` 按阶段（draft / review / revise）注入提示词；支持本地目录、zip、GitHub 安装。
- **MCP**：连接 stdio / HTTP MCP 服务器，工具供写作 Agent 调用。
- 流式 SSE 输出，工具调用过程可追踪。

---

## 快速开始（用户）

### 使用发布包

1. 从 [Releases](https://github.com/YOUR_USER/NovelAgent/releases) 下载 `NovelAgent.exe`（或自行打包，见下文）。
2. 双击运行。
3. 打开 **设置**，配置任意 **OpenAI 兼容** API（OpenAI、DeepSeek、智谱 GLM、Ollama 等）。未配置 Key 时 AI 功能不可用。

**数据目录（默认）**：`%APPDATA%\NovelAgent\`  
作品、设置与 API Key 均保存在本机；重装或替换 exe 一般不会丢失数据。

**便携模式**：启动前设置环境变量，将数据放在指定目录（可与 exe 同目录）：

```powershell
$env:NOVEL_AGENT_DATA = "D:\path\to\data"
.\NovelAgent.exe
```

---

## 从源码运行（开发者）

### 环境要求

- **Node.js** 18+，**pnpm**
- **Python** 3.10+（推荐 3.11）
- Windows（开发与 EXE 打包路径以 Windows 为主）

### 克隆与安装

```powershell
git clone https://github.com/YOUR_USER/NovelAgent.git
cd NovelAgent
```

仓库**不含** `node_modules`、`.venv`、`dist`、本地数据库；克隆后需分别安装依赖（见下）。

可选：开发时将数据放在仓库外的目录，避免误提交：

```powershell
$env:NOVEL_AGENT_DATA = "D:\novel-agent-data"
```

### 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn novel_agent.main:app --port 8765 --reload
```

### 前端

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器访问 <http://localhost:5173>（Vite 已代理到后端 `8765`）。

生产静态资源（EXE 打包或后端直出静态页前**必须**执行）：

```powershell
pnpm build
```

产物为 `frontend/dist/`（由 `.gitignore` 忽略，不进入版本库）。

### 桌面窗口（可选）

开发与 EXE 均通过 `backend/run.py` 启动 uvicorn + pywebview。日常开发一般用「后端 + `pnpm dev`」即可；验证打包行为时再跑 `run.py` 或 `build_exe.ps1`。

---

## 测试

```powershell
cd backend

# 无 API Key：使用 stub 服务器（开发 / CI）
.\.venv\Scripts\python.exe run_stub_server.py
# 另开终端：
.\.venv\Scripts\python.exe tests\e2e_test.py
.\.venv\Scripts\python.exe tests\interview_test.py
.\.venv\Scripts\python.exe tests\book_test.py
.\.venv\Scripts\python.exe tests\tools_test.py
.\.venv\Scripts\python.exe tests\import_test.py

# 针对已打包 EXE 的验收（需设置 NOVEL_AGENT_API_KEY）
$env:NOVEL_AGENT_API_KEY = "sk-..."
powershell -ExecutionPolicy Bypass -File tests\run_frozen.ps1
```

---

## 打包 EXE

```powershell
cd frontend
pnpm build

cd ..\backend
.\.venv\Scripts\python.exe -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

产物：`backend\dist\NovelAgent.exe`（无控制台，目录由脚本创建，不纳入 Git）。

调试版（带控制台）：

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Console
```

生成 `NovelAgent_debug.exe`。脚本会清理旧的 `build/`、`*.spec` 再调用 PyInstaller；无需在仓库中保留 `NovelAgent.spec`。

---

## Agent 工具

### 内置查询（审校 / 写作时核对一致性）

| 工具 | 说明 |
| --- | --- |
| `list_characters` | 列出全部角色 |
| `get_character_details` | 单个角色档案 |
| `get_world_setting` | 世界观设定（可关键词） |
| `list_open_foreshadowing` | 未回收伏笔 |
| `search_previous_chapters` | 前文全文搜索 |
| `get_recent_timeline` | 最近时间线 |
| `get_nearby_chapters` | 前后章梗概与状态 |

### 内置写入（起草 / 修订阶段）

| 工具 | 说明 |
| --- | --- |
| `register_foreshadowing` | 登记新伏笔（去重） |
| `resolve_foreshadowing` | 标记伏笔已回收 |
| `add_timeline_event` | 记录本章关键事件 |

审校阶段仅开放查询类工具；外部 MCP 工具在连接后合并进 Agent 工具列表。

---

## Skills 与 MCP

### Skill 格式（`SKILL.md`）

```markdown
---
name: 技能名
description: 一句话说明
stages: [draft, review, revise]
---

正文会注入对应阶段的系统提示词。
```

安装方式（应用内 **扩展中心**）：本地文件夹 · zip · GitHub 仓库 URL（根目录或一级子目录含 `SKILL.md`）。

**源码中的内置技能**位于 `backend/novel_agent/builtin_skills/`（悬疑伏笔、对话个性化、网文节奏等）。首次运行会复制到用户数据目录下的 `skills/`；该目录属于运行时数据，不要提交到 Git。

### MCP

- **stdio**：命令 + 参数（每行一项）。
- **HTTP**：服务器 URL。

测试用样例：`backend/tests/mock_mcp_server.py`。

### 主要 HTTP API（摘录）

| 能力 | 端点 |
| --- | --- |
| 开书访谈 | `POST /api/interview/next` · `POST /api/interview/compile` |
| 导入预览/落库 | `POST /api/import/preview` · `POST /api/import/commit` |
| 导入分析（SSE） | `POST /api/projects/{pid}/import/analyze` |
| 一键仿写 | `POST /api/projects/{pid}/imitate` |

完整路由见 `backend/novel_agent/routers/`。

---

## 数据与隐私

- API Key 与作品数据保存在**本机** SQLite（默认 `%APPDATA%\NovelAgent\` 或 `NOVEL_AGENT_DATA` 指定路径）。
- 除你配置的模型服务商请求外，本项目不向第三方上传 Key 或正文。
- 开源仓库**不包含** API Key、作品库或运行时 `data/`；勿将 AppData 或本地 `data/` 提交到 Git。

---

## 仓库结构

```
.
├── .gitignore                  # 忽略依赖、构建产物、本地 data/
├── README.md
├── backend/
│   ├── .gitignore
│   ├── run.py                  # EXE 入口（uvicorn + pywebview）
│   ├── run_stub_server.py      # 测试用 LLM stub
│   ├── build_exe.ps1           # PyInstaller 打包
│   ├── requirements.txt
│   ├── novel_agent/            # FastAPI 应用主体
│   │   ├── main.py
│   │   ├── agent.py · book.py · importer.py
│   │   ├── skills.py · mcp.py · tools.py
│   │   ├── routers/
│   │   └── builtin_skills/     # 内置 Skill 源（入仓）
│   └── tests/
├── frontend/
│   ├── .gitignore
│   ├── index.html · vite.config.js
│   ├── package.json · pnpm-lock.yaml
│   ├── public/
│   └── src/                    # Vue 页面与组件
└── website/                    # 项目介绍静态页（可选，与桌面应用独立）
```

**本地生成、不提交的内容**（见下一节）：`backend/.venv`、`backend/build`、`backend/dist`、`frontend/node_modules`、`frontend/dist`、根目录 `data/`（若用便携数据目录指向仓库内路径）。

---

## 版本库与忽略规则

| 路径 | 说明 |
| --- | --- |
| `backend/.venv/` | `python -m venv` 后 `pip install -r requirements.txt` |
| `frontend/node_modules/` | `pnpm install` |
| `frontend/dist/` | `pnpm build`；EXE 打包前必需 |
| `backend/dist/*.exe` | `build_exe.ps1` 产出 |
| `backend/build/`、`backend/*.spec` | PyInstaller 中间文件，打包时自动清理/生成 |
| `data/` | 便携模式或开发时产生的 SQLite、`skills/` 副本 |

根目录与 `backend/`、`frontend/` 均已配置 `.gitignore`。提交前可用 `git status` 确认未包含上述路径。

---

## 参与贡献

欢迎 Issue 与 Pull Request。建议流程：

1. Fork 本仓库，从 `main` 拉分支。
2. 后端改动请跑通 `tests/tools_test.py` 及相关的 e2e/import 测试。
3. 前端改动请确保 `pnpm build` 无报错。
4. PR 请简要说明功能或修复点；涉及 UI 可附截图。

---

## 许可证

本仓库采用 **[MIT License](LICENSE)**。
---

## 相关链接

- Releases：`https://github.com/YOUR_USER/NovelAgent/releases`
- Issues：`https://github.com/YOUR_USER/NovelAgent/issues`

将 `YOUR_USER/NovelAgent` 替换为你的 GitHub 用户名与仓库名。
