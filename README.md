<div align="center">

<img src="assets/logo.svg" width="112" height="112" alt="Lawver" />
<br/>
<img src="assets/logo-wordmark.svg" width="242" height="56" alt="Lawver" />

<p>面向中文法律场景的 AI 助手<br/>把法律问题拆成可核验的事实、依据与分析路径</p>

<p>
  <a href="https://github.com/Hill-1024/Lawyance/releases"><img alt="version" src="https://img.shields.io/badge/version-0.1.21-3b62b8"></a>
  <img alt="license" src="https://img.shields.io/badge/license-AGPL--3.0-A42E2B">
  <img alt="python" src="https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.139%2B-009688?logo=fastapi&logoColor=white">
  <img alt="react" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black">
  <img alt="vite" src="https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white">
  <img alt="tailwind" src="https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white">
  <img alt="capacitor" src="https://img.shields.io/badge/Capacitor-8-119EFF?logo=capacitor&logoColor=white">
</p>

<p>中文 · <a href="./README.en.md">English</a> · <a href="./README.ja.md">日本語</a></p>

</div>

Lawver 是工大法智团队的中文法律 AI 助手项目。它把法律咨询、法条检索、案例匹配、企业信息查询、合同/PDF/Word/TXT/Markdown 文档处理、对话级记忆和前端工作区组织在同一套应用中，目标不是给出无法追溯的“直接结论”，而是把法律问题拆成事实、依据、检索结果和可继续核验的分析路径。

仓库同时包含 FastAPI 后端、React/Vite 前端、工具转发层、法律数据检索客户端、文档处理工具、对话记忆系统和输出审查流程。各模块之间保持清晰边界，业务工具统一通过 `mcps` 暴露给 agent，不在业务层绕过工具中间件。

## 项目定位

- 面向中文法律场景的 AI 助手原型。
- 支持直接回答和 Plan-and-Solve 等不同复杂度的 agent 工作方式。
- 通过工具调用接入法条、案例、企业信息和文档处理能力。
- 通过对话级记忆保留稳定事实、用户约束和当前工作边界。
- 通过前端工作区管理上传文件、生成文件和对话上下文。

## 核心能力

- **法律检索与联网搜索**: 支持法条精确查询、自然语言法条搜索、来源链接确认、案例匹配，以及通过自托管 SearXNG 获取公开网页资料。
- **企业信息**: 接入企业概况、上市信息、联系方式、股东、登记信息、主要人员和对外投资等查询能力。
- **文档处理**: 支持 PDF 文本读取、PDF 句级批注、Word 读取、Word 批注写入，以及 TXT/Markdown 安全读写。
- **Agent 模式**: 支持默认回答和 Plan-and-Solve 分步处理。
- **模拟法庭**: 民事、行政、刑事三类庭审推演，内置法官、对方律师、复盘员、用户方 AI 代理四角色，按阶段状态机推进，公开记录与私有 brief 之间有事实边界，支持撤回与分支会话。
- **会话工作区**: 为每个用户和对话隔离 `TEMP` 与 `Result` 文件空间，避免文件串线。
- **对话级记忆**: 记录和检索稳定事实、目标、约束与语义标签，不把全部历史暴力塞回上下文。
- **认证与审计**: 包含登录、角色、管理员账号管理、API 访问日志、Redis 共享限流，以及用于挡住无效 token 洪水的会话布隆过滤器。
- **前端体验**: React 19 + Vite，提供主聊天、模拟法庭、文件工作区、主题、管理员面板和 Lawver 品牌界面。

## 架构

```text
React / Vite frontend
    |
    | REST / stream / file workspace
    v
FastAPI application
    |
    | agent orchestration
    v
Default / Plan-and-Solve / Court agents
    |
    | tool descriptions + calls
    v
mcps tool forwarding layer
    |
    | legal data / company data / document processors / memory client
    v
MCP clients and local services
```

关键路径：

| 路径 | 说明 |
| --- | --- |
| `agent.py` | 仅保留 `agent:app` 与 `python agent.py` 启动契约，支持 `PORT` 与 `UVICORN_WORKERS` 环境变量 |
| `app_factory.py` | FastAPI 应用工厂，集中注册中间件、路由和生命周期任务 |
| `routes/` | 认证、管理员、聊天、模拟法庭、工作区、SPA fallback 等 HTTP 路由 |
| `services/` | 聊天与庭审流水线、历史压缩、记忆协调、法库缓存、工作区清理、安全中间件 |
| `agents/tool_loop.py` | 统一原生 tool_calls Agent 循环，承载默认模式与 Plan-and-Solve |
| `function_calling.py` | OpenAI 兼容模型调用封装与工具消息配对 |
| `tools/` | 业务工具显式注册表（schema / handler / coercer / exposure） |
| `mcps.py` | 业务工具统一转发入口 |
| `mcp/` | 法律、企业、PDF、Word、TXT/Markdown、记忆、SearXNG 联网搜索等工具客户端 |
| `memory_system/` | 对话级结构化记忆服务 |
| `RAG/` | 本地法律法规检索引擎 |
| `prompts/lawver/` | 核心、模式、焦点、任务、模拟法庭等动态 prompt 资源 |
| `workspace.py` | 工作区路径边界与上传/生成文件验证 |
| `ocp.py` | 输出审查（OCP）流水线 |
| `src/` | React 前端，含主聊天与模拟法庭两个工作流 |
| `tests/` | 覆盖记忆、OCP、工具循环、模拟法庭、安全加固、提示词加载等 |

## 环境要求

- Python 3.13 或更高版本。
- Node.js 与 pnpm。
- Android 客户端打包需要 JDK 21 与 Android SDK。
- 可访问所需模型服务和业务数据源。
- 根目录 `.env` 文件中提供模型 API 密钥等本地配置。

不要把 API Key、账号密码或真实客户材料提交到仓库。可参考 `.env_example` 创建本地 `.env`：

```env
API_KEY="your_api_key_here"
```

## 安装

```bash
pnpm install
pip install -r requirements.txt
```

仓库也包含 `pyproject.toml` 与 `uv.lock`。如果你的本地工作流使用 uv，可以按团队约定改用 uv 安装 Python 依赖。

## 开发运行

构建前端静态资源：

```bash
pnpm run build
```

启动完整应用：

```bash
pnpm run dev
```

该命令会执行 `python agent.py`。如需单独启动 Vite 前端开发服务：

```bash
pnpm run dev:frontend
```

常用脚本：

| 命令 | 说明 |
| --- | --- |
| `pnpm run dev` | 启动 FastAPI 应用 |
| `pnpm run dev:frontend` | 启动前端开发服务 |
| `pnpm run build` | 构建前端 |
| `pnpm run preview` | 预览前端构建产物 |
| `pnpm run lint` | TypeScript 静态检查 |
| `pnpm run clean` | 清理前端构建产物 |
| `pnpm run mobile:doctor` | 检查 Capacitor Android 环境 |
| `pnpm run mobile:android:sync` | 构建前端并同步 Android 资源 |
| `pnpm run mobile:android:test` | 运行 Android debug 单元测试 |
| `pnpm run mobile:android:apk` | 构建 Android debug APK |

## Android APK 发布与更新

Android 正式发布通过 GitHub Actions 的 `vX.Y.Z` 标签工作流构建 release APK。工作流会校验 tag 与 `package.json.version` 一致，使用 GitHub Secrets 中的长期 release keystore 签名，并把 `Lawver-${version}.apk` 与 `android-version.json` 上传到 GitHub Release。

生产后端启动时会从 GitHub 最新 Release 同步 Android APK 到本地缓存目录，默认 `data/releases/android/`，并公开免登录分发接口：

- `GET /api/releases/android/latest`：返回当前缓存版本信息，`apkUrl` 会改写为生产后端下载地址。
- `GET /api/releases/android/apk`：下载当前缓存 APK，按单 IP 默认 6 RPM 限流。

可选环境变量：

- `LAWVER_RELEASE_SYNC_ON_STARTUP`：是否启动时同步 GitHub Release，默认 `1`。
- `LAWVER_RELEASE_REPO`：GitHub Release 来源仓库，默认 `Hill-1024/Lawyance`。
- `LAWVER_RELEASE_DIR`：APK 缓存目录，默认 `data/releases/android/`。
- `LAWVER_PUBLIC_BASE_URL`：对外生产域名，默认按请求推断，兜底取 package.json `appConfig.domain`（当前 `https://lawver.dev`）。
- `LAWVER_APK_DOWNLOAD_RPM`：APK 下载接口单 IP 每分钟限制，默认 `6`。
- `LAWVER_TRUSTED_PROXY_CIDRS`：额外可信反向代理 CIDR，默认只信任 loopback；只有这些来源的 `CF-Connecting-IP` / `X-Forwarded-For` 会用于限流和日志。
- `LAWVER_GITHUB_TOKEN`：私有仓库或 GitHub API 限流时使用的只读 token。

## 聊天断线续传

断线续传默认关闭。用户开启后，每个聊天请求会携带 `resume_enabled=true`，服务端仅在当前进程内临时缓存该回答的 SSE 事件；设备确认写入 IndexedDB 后会 ACK 裁剪，完成并确认收全后删除。

服务端把「读者队列溢出」判为慢读：被断开的读者会收到 `resume_unavailable`（`slow_reader` / `reader_limit`），前端据此按退避重连从缓冲补齐，而不是把回答判成失败。因此队列阈值同时是误判线——调小会把一次读停顿（长回答渲染阻塞、移动网络抖动）当成断流。

可选环境变量：

- `LAWVER_RESUME_MAX_STREAMS_PER_USER`：每用户并发缓冲流，默认 `3`。
- `LAWVER_RESUME_MAX_BYTES_PER_STREAM`：单流缓冲字节，默认 `2097152`。
- `LAWVER_RESUME_MAX_BYTES_GLOBAL`：全局缓冲字节，默认 `134217728`。
- `LAWVER_RESUME_TTL_SECONDS`：缓冲 TTL，默认 `2700`。
- `LAWVER_RESUME_SWEEP_SECONDS`：清扫间隔，默认 `60`。
- `LAWVER_RESUME_MAX_READERS_PER_STREAM`：单流并发读者数，默认 `4`。
- `LAWVER_RESUME_MAX_READER_QUEUE_EVENTS` / `LAWVER_RESUME_MAX_READER_QUEUE_BYTES`：读者队列阈值（即慢读判定线），默认 `256` / `2097152`。
- `LAWVER_RESUME_MAX_EVENTS_PER_STREAM`：单流事件条数上限，默认 `8192`（与硬上限一致，让字节上限决定裁剪，长回答不会中途变成不可续传）。
- `LAWVER_RESUME_REQUIRE_SINGLE_WORKER=1`：当 `UVICORN_WORKERS>1` 时拒绝启动，避免内存续传落到不同 worker。

## 动态 Prompt

Lawver 的系统 prompt 已拆分到 `prompts/lawver/`，后端每次构造对话上下文时都会重新读取这些片段，并在运行时最多拆成三条 system message（稳定前缀 / 动态 memory / recap）：

- `core/`：身份、硬约束、工具信源规则、输出契约、文件处理规则
- `modes/`：`default`、`plan_and_solve` 两种 agent 模式的注意力焦点
- `focus/`：按当前请求动态追加的法律检索、文件处理、任务边界焦点
- `tasks/`：历史摘要等内部任务专用 prompt
- `court/`：模拟法庭通用边界（`common.md`）、案由（`cases/{civil,administrative,criminal}.md`）和角色（`roles/{judge,opponent,reviewer,user_agent}.md`）

工具 schema 不放进动态 prompt，也不从 prompt 目录读取；模型工具能力仍由 `function_calling.call()` 通过 `mcps.py` 中的静态工具常量传入。

可选环境变量：

- `LAWVER_PROMPT_ROOT`：指定完整 prompt 根目录
- `LAWVER_PROMPT_PROFILE`：指定 `prompts/<profile>`，默认 `lawver`
- `LAWVER_PROMPT_INCLUDE_EXAMPLES=1`：将 `examples/` 中的 few-shot 示例追加到系统 prompt

## 后端拓扑与工具注册

后端入口 `agent.py` 只保留 `agent:app` 和 `python agent.py` 启动契约；应用组装在 `app_factory.py`，路由在 `routes/`，聊天流水线、历史压缩、记忆协调和清理任务在 `services/`。

路由注册顺序必须保持为：认证 → 管理员 → 聊天 → 模拟法庭 → APK 发布分发 → 工作区/上传/下载 → SPA catch-all。`routes/spa.py` 的 catch-all 必须最后挂载，避免吞掉 `/api/*`。

业务工具仍统一通过 `mcps.py` 暴露给 agent。新增工具的推荐流程：

1. 在 `mcp/` 中实现真实客户端或处理函数。
2. 在 `tools/__init__.py` 显式注册 schema、handler、参数 coercer 和 `exposure`。
3. 通过 `mcps.use_tools()` 调用，不让 agent、route 或 service 直接绕过 `mcps`。

`exposure` 是工具可见性的唯一声明来源：

- `agent`：LLM 可见工具。
- `plan_and_solve`：Plan-and-Solve 模式可见工具，包含业务工具和控制面工具。
- `court`：模拟法庭流水线（`registry.schemas("court")`）可见工具，包括法律信源、企业、文档、网络搜索、记忆与工作区。
- `ocp_reviewer`：OCP 审查器可用的只读法律信源工具。
- `internal`：后端内部可 dispatch，但不进入 LLM tool schema 的工具。

工作区路径校验集中在 `workspace.py`，`mcps.py` 和 `tools/*` 都依赖它，避免工具注册拆分后产生循环 import。

OCP 是主回复后的格式审查 pass。主模型失败仍按主模型错误路径处理；OCP 自身的超时、网络异常、工具异常或审查模型异常不得向用户路径抛出，必须降级为 deterministic fallback：保留主模型正文，只在本地做 Markdown 表格修复与信源区补建（正文角标自带 URL，可离线反推文末溯源），因此任何降级路径都不会出现「有角标、无溯源」的裸输出。

本次架构边界不包含 Lawver 命名统一、工具命名规范重写或 agent 推理策略重写。

### 调用链与解耦不变量

所有请求只经过两条路由接受和转发，禁止跨模块直连：

```text
routes/  ->  services/  ->  services/agent_builder.py（范式路由）
                                 |-- execute_tool  = mcps.use_tools(..., capability)
                                 |-- output_review = services/ocp_service.build_output_review(...)
                                          |
                                          v 注入
                             agents/ToolLoopAgent（统一 agent 循环，只调用注入的处理器）
                                          |
                                          v
                             mcps.py（唯一能力路由）
                                 |-- tools/registry.py
                                 |-- mcp/* · memory_system/ · RAG/
```

不变量由 `tests/test_architecture_boundaries.py` 锁定：

- 只有 `mcps.py` 与 `tools/**` 可以 import `tools` / `tools.registry`。
- `agents/**` 不得 import `ocp`、`services/**`、`tools`、`mcp`、`memory_system`、`RAG`。
- `tools/**` 不得 import `services/**`。
- `services/**`、`routes/**` 不得直接 import `tools`、`mcp`、`memory_system`、`RAG`、`ocp`，一律经 `mcps` 转发；`ocp` 只允许 `services/ocp_service.py` 构造。
- 生产模块的 import 图无环。
- 中性共享模块（`workspace.py`、`media.py`、`context_usage.py`、`infra/`）不得反向依赖 `services/`。

OCP 与 default / plan_and_solve / court 同构：由 `services/agent_builder.py` 解析成 `output_review` 注入 `ToolLoopAgent`，agent 循环不直接 import `ocp`。已知例外：主模型与 OCP 的模型档案读取（`function_calling` / `services.ocp_service` → `services.settings_service`）保留为配置存储依赖，它不反向依赖调用方，不构成环。

联网搜索工具通过自托管 SearXNG 提供，不依赖 Tavily、SerpAPI 等第三方搜索 API。`web_search` 只返回结构化搜索结果和 snippets；需要阅读网页正文时由模型再调用 `web_fetch`。`web_fetch` 返回内容会被标记为非可信网页数据，不能作为指令执行。

TXT/Markdown 文件通过 `txt_md_reader` / `txt_md_writer` 处理，只能访问当前对话工作区；读取和写入都会过滤 Markdown/HTML 中的可执行嵌入内容，例如 `<script>`、事件处理属性和 `javascript:` / `data:` 链接。

可选环境变量：

- `SEARXNG_BASE_URL`：SearXNG 实例地址，默认 `https://serp.mutsumi.moe/`
- `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`：Cloudflare Access Service Auth 头；兼容旧的 `SEARXNG_CF_ACCESS_CLIENT_ID` / `SEARXNG_CF_ACCESS_CLIENT_SECRET`
- `SEARXNG_ENGINES`、`SEARXNG_CATEGORIES`、`SEARXNG_LANGUAGE`、`SEARXNG_SAFE_SEARCH`：默认搜索参数覆盖；通常让服务端 `settings.yml` 和 `categories` 路由决定 engines，仅在需要固定精确引擎时设置 `SEARXNG_ENGINES`
- `SEARXNG_TIMEOUT`、`SEARXNG_MAX_RESULTS`、`SEARXNG_MAX_RESPONSE_BYTES`：请求和结果规模限制，默认搜索超时 20 秒、结果数 10 条

管理后台保存的 provider 配置优先于环境变量：启动时与保存后都会同步到运行时进程，环境变量作为回退（配置被清空时自动还原）。本地/内网地址（如 `http://localhost:10099`）不需要 Cloudflare Access Token，不会因缺少 token 而报配置错误。

## 对话记忆与 RAG 权重

记忆系统仍以对话级结构化记忆为主，召回时会融合关键词、语义标签、实体、时效、优先级和焦点等多路信号。可选开启 embedding 召回后，向量相似度会作为其中一路 `embedding` 信号进入同一套 RAG 权重排序，而不是替换现有多路召回。

可选环境变量：

- `MEMORY_EMBEDDING_ENABLED=1`：启用 embedding 召回权重，默认关闭
- `EMBEDDING_API_KEY`：embedding 服务 API Key
- `EMBEDDING_BASE_URL`：embedding 服务 OpenAI-compatible Base URL，默认 `https://api.siliconflow.cn/v1`
- `EMBEDDING_MODEL`：embedding 模型，默认 `Qwen/Qwen3-Embedding-8B`
- `MEMORY_EMBEDDING_TIMEOUT`：embedding 请求超时时间，默认 8 秒

## 模拟法庭

模拟法庭是一个由多 AI 角色合作的庭审推演工作流，与主聊天共享工作区和工具集，但走独立的 prompt 与流水线。

- **三类案由**：民事、行政、刑事，每类按阶段状态机推进（开庭 → 诉辩陈述/起诉 → 法庭调查 → 举证质证/合法性审查 → 法庭辩论 → 最后陈述 → 法庭意见 → 庭后复盘）。
- **四角色记忆隔离**：法官、对方律师、复盘员、用户方 AI 代理（可选开启）各自拥有独立的私有记忆 scope，公开发言进入共享庭审记录。
- **事实与法源边界**：角色发言只能基于共享卷宗、公开庭审记录与工具返回结果，未公开事实需标注「待核实」；对方律师可提出可能事实假设，但必须用「可能/不排除/请法庭查明」等限定语。
- **撤回与分支**：可回退到任意公开事件后重算结构化状态并清空 AI 私有记忆；也可以从该点派生新庭审 session，共享卷宗但独立推进。

后端入口为 `routes/court.py`，流水线在 `services/court_pipeline.py` 与 `services/court_fsm.py`；前端在 `src/components/CourtPage.tsx` 与 `src/hooks/useCourtSession.ts`。

## 测试

```bash
python -m pytest
```

当前测试套件约 440 个用例，按模块大致覆盖：

- `tests/test_memory_system.py`、`tests/test_prompt_loader.py`：对话级记忆与动态 prompt 装配。
- `tests/test_ocp.py`、`tests/test_tool_loop_agent.py`：输出审查与统一工具循环。
- `tests/test_court_mode.py`：模拟法庭阶段状态机与角色边界。
- `tests/test_security_hardening.py`、`tests/test_mcps_workspace_paths.py`、`tests/test_remaining_vulnerability_fixes.py`：CSRF、限流、工作区路径与历史漏洞回归。
- `tests/test_request_shielding.py`：布隆过滤器假阴性边界、共享限流、Redis 降级与无效 token 的免回源拒绝。Redis 分支需要 `fakeredis`（见 `requirements-dev.txt`），缺失时自动跳过。
- `tests/test_function_calling_tools.py`、`tests/test_tool_schema_compatibility.py`、`tests/test_tool_exposure.py`：工具 schema、exposure 与 OpenAI 兼容性。
- `tests/test_law_data_search.py`、`tests/test_law_cache_startup.py`、`tests/test_searxng_tool.py`：本地法库检索、缓存增量与 SearXNG 客户端。

## 开发边界

- `mcps.py` 是业务工具面向 agent 的统一入口。新增工具时应先接入 `mcp/` 客户端，再由 `mcps` 暴露，而不是让 agent 或业务接口直接绕过。
- 记忆系统当前定位是对话级结构化记忆，不是用户级长期画像；可选 embedding 只作为召回权重信号参与排序。
- 上传文件和生成文件必须落在用户/对话隔离的工作区内，避免跨会话读取或写入。
- 法律回答应尽量保留依据链路：事实、法条、案例或来源链接要能被继续核验。
- 前端迁移和 UI 调整应尊重 Lawver 设计系统，不通过 padding 或临时兼容层掩盖布局问题。
- 页面返回必须走 `src/hooks/useAppBack.ts`（决策逻辑在同目录 `src/lib/app-history.ts`），不要在返回按钮里直接写 `navigate(父级路径)`。后者会往 history 栈压入新记录，用户再按返回就会「前进」回刚离开的子页，表现为返回错乱、需连按多次才能退出。规则由 `pnpm run test:app-back` 锁定：栈内有记录时退栈；深链/刷新进入（history idx 为 0）时改用 replace 落到父级，避免退栈离开应用；已在根路由则交由调用方退出应用。

## 账号与权限

账号、密码摘要与在线会话统一存放在 `data/` 下的 SQLite 数据库 `auth.sqlite3`，与 `secrets.json`、`settings.json`、`lockout.json` 同级，不再使用 `data/account.json`。首次启动时若账号库为空且存在遗留的 `account.json`，会自动导入并把该文件改名为 `account.json.imported-<时间戳>`（角色 `admin` 会映射为 `sudo`）。

权限分三级，形成 `sudo → admin → user` 的层级：

- `sudo`（超级管理员）：全部权限，包括查看使用日志、管理所有账号、给 admin 设定配额 n / m、给 user 覆写在线设备上限、踢任意设备，以及系统与模型设置。内置账号用户名为 `admin`，角色为 `sudo`，不可删除。
- `admin`（管理员）：只能管理自己创建的 user，可创建的用户数量上限为 n，可重置密码、删除、踢下线；不能创建 admin/sudo，不能修改 m，也看不到日志与系统设置。
- `user`：仅使用。

在线设备限制：每个账号可登录的设备数受其「最大在线设备数」约束（留空/0 表示不限制）。登录产生一条会话记录，最近活跃时间在 `LAWVER_ONLINE_WINDOW_SECONDS`（默认 900 秒）内计为在线；超限时默认踢掉最久未活跃的设备（`LAWVER_ONLINE_LIMIT_ACTION=reject` 可改为拒绝新登录）。登出、改密码、改角色或删除账号都会立即作废相应会话。

## 请求防护（限流与布隆过滤器）

针对「大量无效请求打穿后端」，服务端有两层前置防护，二者都会随 Redis 可用性自动降级：

**1. 共享限流**：所有 `/api` 请求按客户端 IP 计数（默认 100 次/分钟），`POST /api/login` 另有更严格的登录桶（默认 30 次/分钟）。登录桶是为了挡住同一 IP 跨用户名撞库——账号级锁定只保护单个账号，拦不住用户名喷洒。Android APK 下载同样走这套计数（默认 6 次/分钟，可用 `LAWVER_APK_DOWNLOAD_RPM` 调整）。命中限流返回 429 并带 `Retry-After`，且发生在读取请求体之前。

**2. 会话布隆过滤器**：JWT 里的 `sid` 先过一张位图，位图判定「不存在」的 token 直接拒绝，不再打开 SQLite。它只增不删，并且只在预热完成、位图与就绪标记同时存在时才参与判断：Redis 键被淘汰、预热中断或命令报错时一律放行给数据库裁决。因此假阴性（误杀有效登录）不会发生，假阳性只是多查一次库。

配置 Redis 后，限流计数与会话位图由所有 worker / 实例共享；未配置 `LAWVER_REDIS_URL` 时退回进程内实现，单 worker 行为与旧版一致。Redis 只是防护层：URL 写错、连不上或命令报错都会在冷却窗口内自动降级，不影响登录与鉴权。使用普通 Redis 即可，不需要 RedisBloom 模块——位图由 `SETBIT` / `GETBIT` 实现。

可选环境变量：

- `LAWVER_REDIS_URL`（兼容 `REDIS_URL`）：Redis 连接串，例如 `redis://127.0.0.1:6379/0`；未设置时全部退回进程内。
- `LAWVER_REDIS_PREFIX`：键前缀，默认 `lawver`。
- `LAWVER_REDIS_TIMEOUT`：单次 Redis 命令超时秒数，默认 `0.25`；Redis 卡住时最多给每个请求增加这点延迟。
- `LAWVER_API_RATE_LIMIT`：全局 API 单 IP 每分钟上限，默认 `100`。
- `LAWVER_LOGIN_RATE_LIMIT`：登录接口单 IP 每分钟上限，默认 `30`。
- `LAWVER_RATE_LIMIT_ENABLED`：设为 `0` 完全关闭限流（仅建议测试环境）。
- `LAWVER_BLOOM_ENABLED`：设为 `0` 关闭会话布隆过滤器，每个请求都回源数据库。
- `LAWVER_BLOOM_SESSION_CAPACITY`：位图容量，默认 `200000`，按有效会话数量级估算。
- `LAWVER_BLOOM_ERROR_RATE`：误判率，默认 `0.001`。

启动日志会打印实际生效的后端：`Redis 请求防护：available=... prefix=...` 与 `会话布隆过滤器预热完成：...`。

## 部署拓扑：主机名分机 + 本机分流核心

介绍页与功能页是两个仓库、两个进程，同一个域名对外：

```
lawver.dev          → 隧道 → 国内机器：分流核心 8080 ─┬─ 介绍页进程 8082（Hill-1024/Lawyance_Intro）
global.lawver.dev   → 隧道 → 海外机器：分流核心 8080 ─┴─ 功能页进程 8081（本仓库，FastAPI）
```

- **跨机分流靠主机名**：`lawver.dev` 与 `global.lawver.dev` 各自指向一台机器的隧道入口；两台机器跑同一套布局，差异只有主机名与数据源。原先按 `/cn`、`/asean` 路径前缀分流的方案已退役——前缀会渗进前端路由、SW scope 与资源基准三处，纯属把复杂度搬进应用；主机名分流把这件事留在 DNS 层。
- **本机分流靠路径**：每台机器上的 [deploy/router](deploy/router/README.md) 是唯一入口，监听稳定端口 8080，把介绍页路径（`/`、`/design`、`/download`、`/pricing`、`/robots.txt`、`/sitemap.xml`、`/intro-assets/*`）交给介绍页进程，其余（`/home`、`/login`、`/settings/*`、`/admin`、`/business`、`/court/*`、`/api/*`…）交给功能页进程。以后任一侧怎么重启换代，隧道配置都不用动。
- **端口**：核心 8080（`appConfig.routerPort`）、功能页 8081（`appConfig.port`）、介绍页 8082（`appConfig.introPort`）。功能页只监听回环，不直接对外。
- **维护兜底**：任一侧下线（或 `state_dir` 下的 `<side>.maintenance` 开关文件在，生产为 `/var/lib/lawver/router-state/<side>.maintenance`）时，核心把页面导航 302 到 `/under_maintenance`（「维护中／我们很快就会回来。」，恢复后自动跳回原路径），接口与静态资源返回 503 JSON + `Retry-After`。核心自己回答这个页面，所以两侧都挂时它仍然可用。
- **`<base>` 与资源路径**：功能页仍由 `backend/routes/spa.py` 注入 `<base href="/">`，深链接（`/court/xxx`、`/settings/profile`）才会解析出正确资源；介绍页构建用绝对路径（`base: '/'`），产物落在 `/intro-assets/*`，与功能页的 `/assets/*` 不撞——同域下两个构建不能共用 `/assets`。
- **探活**：功能页提供 `/api/health`（免鉴权、不碰数据库、不写访问日志），介绍页提供 `/healthz`；核心每 5s 探一次，页面导航遇到某一侧下线时立刻给维护页。

## 部署运行手册（远端机器）

给在部署机上工作的执行者（人或 agent）：从零到上线照这个顺序做，每一步都给了验收方式。本文按 Debian 12 / Ubuntu 22.04 写，其他发行版把包管理命令换掉即可。

### 0. 名词与端口

| 名称 | 目录 | 端口 | 对外 |
|---|---|---|---|
| 分流核心 | `/srv/lawver/deploy/router` | 8080 | **隧道唯一入口** |
| 功能页 | `/srv/lawver`（本仓库） | 8081 | 只监听回环 |
| 介绍页 | `/srv/lawver-intro`（`Hill-1024/Lawyance_Intro` 的 `dev`） | 8082 | 只监听回环 |

三件套都只监听 `127.0.0.1`，公网流量一律经隧道落到 8080。`lawver.dev` 与 `global.lawver.dev` 各是一台机器，两台跑同一套布局。

### 1. 前置条件

- 系统用户与目录（非 root 运行）：

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin lawver
sudo mkdir -p /srv /var/lib/lawver/{workbench-blobs,backups,router-state}
sudo chown -R lawver:lawver /srv /var/lib/lawver
```

- 软件：`git`、**Python ≥ 3.13**、**Node ≥ 20 + pnpm 10.33.2**（介绍页要构建）、**PostgreSQL 17**，可选 Redis（多 worker 时必需）、可选 Docker（用来跑 `deploy/workbench/compose.yml`）。

```bash
# Node 与 pnpm（Debian/Ubuntu：先装 Node 20+）
corepack enable && corepack prepare pnpm@10.33.2 --activate
```

### 2. 拉代码（两个仓库各自独立）

```bash
sudo -u lawver git clone --branch dev https://github.com/Hill-1024/Lawyance.git       /srv/lawver
sudo -u lawver git clone --branch dev https://github.com/Hill-1024/Lawyance_Intro.git /srv/lawver-intro
```

两个仓库互不依赖：功能页更新不影响介绍页，反之亦然——这正是分开拉取的目的。之后所有 `git pull` 都在各自目录里做。

### 3. Python 依赖

```bash
sudo -u lawver python3 -m venv /srv/lawver/.venv
sudo -u lawver /srv/lawver/.venv/bin/pip install -U pip
sudo -u lawver /srv/lawver/.venv/bin/pip install -r /srv/lawver/requirements.txt
```

### 4. 数据库

```bash
# 方式 A：Docker（deploy/workbench/compose.yml）
cd /srv/lawver/deploy/workbench
LAWVER_POSTGRES_PASSWORD='<强密码>' docker compose up -d

# 方式 B：本机 PostgreSQL 17
sudo -u postgres createuser --pwprompt lawver
sudo -u postgres createdb --owner=lawver lawver
```

跑迁移（**必须在 `backend/` 下执行**，`alembic.ini` 在那里）：

```bash
cd /srv/lawver/backend
sudo -u lawver env LAWVER_DATABASE_URL='postgresql+psycopg://lawver:<密码>@127.0.0.1:5432/lawver' \
  /srv/lawver/.venv/bin/alembic -c alembic.ini upgrade head
```

账号与会话表（`accounts` / `account_sessions`）就在这个库里：**没配 `LAWVER_DATABASE_URL` 就没人能登录**，服务照常起、界面会提示「工作台尚未就绪」。首次启动若账号表为空，会依次尝试导入遗留的 `data/account.json`、`data/auth.sqlite3`，都没有才用 `INITIAL_ADMIN_PASSWORD` 引导出 `admin`。

### 5. 功能页配置 `/srv/lawver/.env`

应用自己用 python-dotenv 读**工作目录下的 `.env`**，所以文件放 `/srv/lawver/.env`、属主 `lawver`、权限 `600`。systemd 单元刻意不用 `EnvironmentFile`（systemd 的环境文件解析与 dotenv 不同——引号与 `*` 的语义不一样，双份来源只会让问题更难查）。

必填：

| 键 | 说明 |
|---|---|
| `SECRET_KEY` | ≥32 位随机串 |
| `INITIAL_ADMIN_PASSWORD` | 只在首次引导账号表时生效，**引导完就删掉这一行** |
| `LAWVER_DATABASE_URL` | 同第 4 步，`postgresql+psycopg://…` |
| `LAWVER_BLOB_DIR` | 建议 `/var/lib/lawver/workbench-blobs` |
| `LAWVER_WORKBENCH_USERS` | 灰度名单，如 `admin`；验收通过后再改 `*` |
| `LAWVER_CONNECTOR_KEY` | 插件凭据加密密钥（Fernet），**与数据库分开保管，丢了就解不开插件凭据** |

按需：模型与检索凭据（`API_KEY` / `BASE_URL` / `LLM_MODEL` / `DELI_*` / `PKU_ACCESS_TOKEN` / `QCC_ACCESS_TOKEN` 等），可选 `LAWVER_REDIS_URL`、`LAWVER_PUBLIC_BASE_URL=https://lawver.dev`、`UVICORN_WORKERS`。完整键名见 `.env_example` 与 `deploy/workbench/environment.example`。

两个坑：

- **不要在 `.env` 里设 `PORT`。** 端口以 `package.json` 的 `appConfig.port`（8081）为准；写成 8080 会和核心抢端口，症状是核心起不来。
- **部署机要设 `LAWVER_HOST=127.0.0.1`。** 功能页默认绑 `0.0.0.0`（方便本地开发直连），部署机上必须收回回环——对外只允许分流核心 8080 经隧道暴露，8081/8082/8083 不该被公网摸到。
- **`UVICORN_WORKERS>1` 时必须配 `LAWVER_REDIS_URL`**，否则限流与布隆过滤器变成每 worker 一份，真实上限被放大到 worker 数倍。

### 6. 介绍页构建与换版

```bash
sudo -u lawver bash -c 'cd /srv/lawver-intro && tools/build.sh'
```

产物进 `releases/<时间戳>/`，然后原子翻转 `current` 符号链接；`server/serve.py` 每个请求解析一次链接，所以**换版零停机、不用重启进程**。构建失败时 `current` 不动，线上继续跑上一版。保留最近 3 个版本（`LAWVER_INTRO_KEEP` 可调）。

### 7. 分流核心配置

```bash
sudo -u lawver cp /srv/lawver/deploy/router/config.example.json /srv/lawver/deploy/router/config.json
```

改这几项，其余保持默认：

| 字段 | 值 |
|---|---|
| `state_dir` | `/var/lib/lawver/router-state` |
| `port` | `8080`（隧道入口，不要改） |
| `app_upstream` / `intro_upstream` | `http://127.0.0.1:8081` / `http://127.0.0.1:8082` |
| `intro_exact` / `intro_prefixes` | 与介绍页仓 README 的路径表保持一致，改一边就要改另一边 |

自检（探活一次并打印状态后退出）：

```bash
/srv/lawver/.venv/bin/python /srv/lawver/deploy/router/router.py \
  --config /srv/lawver/deploy/router/config.json --check
```

### 8. 三个 systemd 服务

单元文件都在仓库里，复制到 `/etc/systemd/system/` 后按部署机实际路径与用户改一遍：

```bash
sudo cp /srv/lawver/deploy/router/systemd/lawver-router.service /etc/systemd/system/
sudo cp /srv/lawver/deploy/systemd/lawver-app.service          /etc/systemd/system/
sudo cp /srv/lawver-intro/deploy/lawver-intro.service          /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now lawver-router lawver-app lawver-intro
systemctl status lawver-router lawver-app lawver-intro --no-pager
```

- `lawver-router`：**`Restart=always`**。它是整站入口，它挂了整站只剩 Cloudflare 的错误页。
- `lawver-app`：工作目录是仓库根（`.env` 与 `data/` 都在这里解析），崩溃自动重启。
- `lawver-intro`：只在改了 `server/serve.py` 时才需要重启，换版走符号链接。

期望日志（`journalctl -u lawver-router -f`）：`分流核心监听 127.0.0.1:8080 → 功能页 http://127.0.0.1:8081、介绍页 http://127.0.0.1:8082`。

### 9. 隧道与 DNS

隧道 ingress（在跑 cloudflared 的那台机器上，或 Cloudflare 面板里）把这些主机名指向本机回环：

| 主机名 | 目标 |
|---|---|
| `cn-origin.lawver.dev` | `http://127.0.0.1:8080`（**保持现状**：它已经指向本机 8080，切换前先用它自检；已安装的 Android 客户端也仍在直连它） |
| `lawver.dev` | `http://127.0.0.1:8080`（从 Cloudflare Pages 切过来） |
| `global.lawver.dev`（海外机） | `http://127.0.0.1:8080` |

执行顺序：先把三件套起好、用 `cn-origin.lawver.dev` 验完（第 10 步），再把 `lawver.dev` 指过来并**移除该主机名上原有的 Worker 路由**（老方案的 `/home → home.lawver.dev` 308 会随之消失）。先切隧道再删 Worker 会有一小段 502，先删 Worker 则会有一小段指向旧站的空窗——按你能接受的顺序做，别两边同时改。

### 10. 上线自检

```bash
# 切换前用 cn-origin 自检（它已经指向本机 8080）；切到 lawver.dev 后把 BASE 换掉再跑一遍
BASE=https://cn-origin.lawver.dev

# 1) 两侧状态（期望 status: ok，sides.app.up 与 sides.intro.up 都是 true）
curl -s 127.0.0.1:8080/__core/status | python3 -m json.tool

# 2) 三条路径走一遍（期望：状态码 200/200/200，归属依次是 intro / app / app）
for p in / /home /api/plans; do
  printf '%-12s %s  %s\n' "$p" \
    "$(curl -s -o /dev/null -w '%{http_code}' $BASE$p)" \
    "$(curl -s -o /dev/null -D - $BASE$p | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
done

# 3) 全链路彩排：自起隔离实例，不动线上（期望「通过 35，失败 0」）
INTRO_REPO=/srv/lawver-intro bash /srv/lawver/deploy/router/rehearsal.sh
```

第 3 步会自己起功能页（18081）、介绍页（18082）与一个独立核心（18080），逐项验路径分派、大文件逐字节、杀一侧不影响另一侧、维护跳转、自动恢复与计划维护开关，跑完自动清理——**这是上线前唯一需要的端到端验收**。

### 11. 日常维护

**更新功能页**（会短暂中断服务，几秒到十几秒）：

```bash
sudo -u lawver bash -c 'cd /srv/lawver && git pull'
sudo -u lawver /srv/lawver/.venv/bin/pip install -r /srv/lawver/requirements.txt   # 依赖有变时
cd /srv/lawver/backend && sudo -u lawver env LAWVER_DATABASE_URL='<同第 4 步>' \
  /srv/lawver/.venv/bin/alembic -c alembic.ini upgrade head                        # 有迁移时
sudo systemctl restart lawver-app
```

**更新介绍页**（零停机，不重启进程）：

```bash
sudo -u lawver bash -c 'cd /srv/lawver-intro && git pull && tools/build.sh'
```

**更新核心**（只有核心代码变了才需要，重启只占几十毫秒）：

```bash
sudo -u lawver bash -c 'cd /srv/lawver && git pull'
sudo systemctl restart lawver-router
```

**维护窗口**：

| 目的 | 做法 |
|---|---|
| 只读维护（功能页仍可读、写操作被拒） | 在 `.env` 里 `LAWVER_WORKBENCH_READ_ONLY=1` 并重启 `lawver-app` |
| 整侧维护（不动进程，用户看到维护页） | `sudo -u lawver touch /var/lib/lawver/router-state/app.maintenance`（介绍页同理换 `intro.maintenance`），撤销就删文件。开关文件在配置的 `state_dir` 下（第 7 步已设为 `/var/lib/lawver/router-state`），不在仓库目录里 |
| 通知用户 | 管理面板发「开屏公告」 |

**备份与恢复**：见 [docs/workbench/operations.md](docs/workbench/operations.md)。要点是每日先切只读、再 `python -m workbench.maintenance backup /var/lib/lawver/backups/$(date +%F)` 并用 `verify` 校验，保留 30 天；`LAWVER_CONNECTOR_KEY` 与备份分开保管。

**日志与观测**：

```bash
journalctl -u lawver-router -u lawver-app -u lawver-intro -f
curl -s 127.0.0.1:8080/__core/status | python3 -m json.tool   # 适合直接挂监控
```

**回滚**：

| 对象 | 做法 |
|---|---|
| 介绍页 | `current` 指回上一个 `releases/<时间戳>`；或 `git pull` 到上一个提交后重跑 `tools/build.sh` |
| 功能页 | `git checkout <上一个 tag>` + 重跑依赖与迁移（迁移是增量新增，**不支持破坏性 downgrade**）+ 重启 |
| 介绍页整站 | 把 `lawver.dev` 在隧道/DNS 层指回 `lawver-intro.pages.dev`（Astro 站与 `main` 分支一直保持在线） |

### 12. 故障排查

| 症状 | 判断 | 处置 |
|---|---|---|
| `/home` 打不开但 `/` 正常 | 功能页下线，核心已自动给维护页 | `systemctl status lawver-app`、`journalctl -u lawver-app -n 100` |
| `/` 显示维护页但 `/home` 正常 | 介绍页下线 | `systemctl status lawver-intro` |
| 两侧都进维护 | 看 `/__core/status` 的 `reason`：`probe failed: ConnectError` = 进程没起或端口不通；`planned` = 开关文件还在 | 按 reason 处置；忘了撤开关就删 `state/*.maintenance` |
| 页面能开但白屏 / 变成下载文件 | Content-Type 或产物缺失 | `curl -sI 127.0.0.1:8082/` 应为 `text/html`；`/intro-assets/<真实文件名>` 应为 `text/javascript` |
| 登录后一直「工作台尚未就绪」 | `LAWVER_DATABASE_URL` 没配或 PG 不可达 | 核对 `.env`、`systemctl restart lawver-app` |
| 所有人都登不进 | 迁移没跑，或账号表为空 | 跑第 4 步迁移；确认 `INITIAL_ADMIN_PASSWORD` 引导过 |
| 全站 502 / 超时 | 核心没起，或别的进程占着 8080 | `ss -ltnp \| grep 8080`、`journalctl -u lawver-router` |
| 想确认某请求落到哪一侧 | 响应头 `X-Core-Upstream: app\|intro` | 不用猜 |

### 13. 禁止事项

- 不要把隧道指向 8081 / 8082——它们是回环上的内部端口，且没有核心的维护兜底。
- 不要在 `.env` 里设 `PORT`，也不要用 8080 起功能页（会和核心抢端口）。
- 不要 `pkill -f agent.py`：机器上可能同时跑着别的实例，统一用 `systemctl`。
- 不要删除 `releases/` 里正被 `current` 指向的目录。
- 不要为了「省事」把 `LAWVER_CONNECTOR_KEY` 存进备份目录。

## 安全注意

- `.env`、真实合同、客户材料、生成结果和日志都可能包含敏感信息，不应随意提交。
- 首次部署必须配置 `SECRET_KEY`（至少 32 位随机值）和一次性的 `INITIAL_ADMIN_PASSWORD`；账号库创建后应移除初始密码环境变量。
- 来源控制（CORS / Origin 校验）不在应用内实现，统一由网关层（反向代理/CDN）配置；应用内保留限流、JSON 体限长与访问日志等防护。
- 默认只从 loopback 代理读取 `CF-Connecting-IP` / `X-Forwarded-For`；如果生产反代不在本机，请通过 `LAWVER_TRUSTED_PROXY_CIDRS` 明确列入。
- 限流计数与会话布隆过滤器默认是进程内状态。多 worker（`UVICORN_WORKERS>1`）或多实例部署应配置 `LAWVER_REDIS_URL`，否则每个 worker 各自计数，真实上限会被放大到 worker 数量倍。
- 后台接口具备账号管理和日志读取能力，`/api/admin/logs` 仅限 sudo，账号与设备接口 sudo/admin 按层级受限，应只暴露给可信人员。
- 文件批注、文档读取和下载接口需要持续关注路径隔离和权限边界。

## 许可证

本项目源代码根据 GNU Affero General Public License v3.0（AGPL-3.0）开源，详见 [LICENSE](./LICENSE)。

复用、修改、分发或以网络服务形式对外提供本项目时，请遵守 AGPL-3.0 的条款。业务数据、第三方数据源、模型服务和真实客户材料不因本仓库许可证自动获得授权，使用前仍需分别确认团队授权和数据合规要求。
