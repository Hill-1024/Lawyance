# Lawver

中文 | [English](./README.en.md) | [日本語](./README.ja.md)

Lawver 是工大法智团队的中文法律 AI 助手项目。它把法律咨询、法条检索、案例匹配、企业信息查询、合同/PDF/Word 文档处理、对话级记忆和前端工作区组织在同一套应用中，目标不是给出无法追溯的“直接结论”，而是把法律问题拆成事实、依据、检索结果和可继续核验的分析路径。

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
- **文档处理**: 支持 PDF 文本读取、PDF 句级批注、Word 读取和 Word 批注写入。
- **Agent 模式**: 支持默认回答和 Plan-and-Solve 分步处理。
- **模拟法庭**: 民事、行政、刑事三类庭审推演，内置法官、对方律师、复盘员、用户方 AI 代理四角色，按阶段状态机推进，公开记录与私有 brief 之间有事实边界，支持撤回与分支会话。
- **会话工作区**: 为每个用户和对话隔离 `TEMP` 与 `Result` 文件空间，避免文件串线。
- **对话级记忆**: 记录和检索稳定事实、目标、约束与语义标签，不把全部历史暴力塞回上下文。
- **认证与审计**: 包含登录、角色、管理员账号管理、API 访问日志和基础限流。
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
| `mcp/` | 法律、企业、PDF、Word、记忆、SearXNG 联网搜索等工具客户端 |
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

路由注册顺序必须保持为：认证 → 管理员 → 聊天 → 模拟法庭 → 工作区/上传/下载 → SPA catch-all。`routes/spa.py` 的 catch-all 必须最后挂载，避免吞掉 `/api/*`。

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

OCP 是主回复后的格式审查 pass。主模型失败仍按主模型错误路径处理；OCP 自身的超时、网络异常、工具异常或审查模型异常不得向用户路径抛出，必须降级为 deterministic sanitizer-only fallback，保留主模型正文。

本次架构边界不包含 Lawver 命名统一、工具命名规范重写或 agent 推理策略重写。

联网搜索工具通过自托管 SearXNG 提供，不依赖 Tavily、SerpAPI 等第三方搜索 API。`web_search` 只返回结构化搜索结果和 snippets；需要阅读网页正文时由模型再调用 `web_fetch`。`web_fetch` 返回内容会被标记为非可信网页数据，不能作为指令执行。

可选环境变量：

- `SEARXNG_BASE_URL`：SearXNG 实例地址，默认 `https://serp.mutsumi.moe/`
- `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`：Cloudflare Access Service Auth 头；兼容旧的 `SEARXNG_CF_ACCESS_CLIENT_ID` / `SEARXNG_CF_ACCESS_CLIENT_SECRET`
- `SEARXNG_ENGINES`、`SEARXNG_CATEGORIES`、`SEARXNG_LANGUAGE`、`SEARXNG_SAFE_SEARCH`：默认搜索参数覆盖；通常让服务端 `settings.yml` 和 `categories` 路由决定 engines，仅在需要固定精确引擎时设置 `SEARXNG_ENGINES`
- `SEARXNG_TIMEOUT`、`SEARXNG_MAX_RESULTS`、`SEARXNG_MAX_RESPONSE_BYTES`：请求和结果规模限制，默认搜索超时 20 秒、结果数 10 条

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

当前测试套件约 170 个用例，按模块大致覆盖：

- `tests/test_memory_system.py`、`tests/test_prompt_loader.py`：对话级记忆与动态 prompt 装配。
- `tests/test_ocp.py`、`tests/test_tool_loop_agent.py`：输出审查与统一工具循环。
- `tests/test_court_mode.py`：模拟法庭阶段状态机与角色边界。
- `tests/test_security_hardening.py`、`tests/test_mcps_workspace_paths.py`、`tests/test_remaining_vulnerability_fixes.py`：CSRF、限流、工作区路径与历史漏洞回归。
- `tests/test_function_calling_tools.py`、`tests/test_tool_schema_compatibility.py`、`tests/test_tool_exposure.py`：工具 schema、exposure 与 OpenAI 兼容性。
- `tests/test_law_data_search.py`、`tests/test_law_cache_startup.py`、`tests/test_searxng_tool.py`：本地法库检索、缓存增量与 SearXNG 客户端。

## 开发边界

- `mcps.py` 是业务工具面向 agent 的统一入口。新增工具时应先接入 `mcp/` 客户端，再由 `mcps` 暴露，而不是让 agent 或业务接口直接绕过。
- 记忆系统当前定位是对话级结构化记忆，不是用户级长期画像；可选 embedding 只作为召回权重信号参与排序。
- 上传文件和生成文件必须落在用户/对话隔离的工作区内，避免跨会话读取或写入。
- 法律回答应尽量保留依据链路：事实、法条、案例或来源链接要能被继续核验。
- 前端迁移和 UI 调整应尊重 Lawver 设计系统，不通过 padding 或临时兼容层掩盖布局问题。

## 安全注意

- `.env`、真实合同、客户材料、生成结果和日志都可能包含敏感信息，不应随意提交。
- 首次部署必须配置 `SECRET_KEY`（至少 32 位随机值）和一次性的 `INITIAL_ADMIN_PASSWORD`；创建 `data/account.json` 后应移除初始密码环境变量。
- 默认 CORS、限流和认证策略适合内部原型阶段，公开部署前需要按实际域名和安全策略收紧。
- 所有非 GET 的 `/api` 请求都要求可信 Origin 或 Referer。可通过 `LAWVER_ALLOWED_ORIGINS`（兼容 `ALLOWED_ORIGINS`）追加生产前端域名；本地开发回环地址默认放行。
- 限流计数为进程内状态，多 worker 部署（`UVICORN_WORKERS>1`）时各 worker 各自计数，公开部署应迁到 Redis 或共享存储。
- 管理员接口具备账号管理和日志读取能力，应只暴露给可信管理员。
- 文件批注、文档读取和下载接口需要持续关注路径隔离和权限边界。

## 许可证

本项目源代码根据 GNU Affero General Public License v3.0（AGPL-3.0）开源，详见 [LICENSE](./LICENSE)。

复用、修改、分发或以网络服务形式对外提供本项目时，请遵守 AGPL-3.0 的条款。业务数据、第三方数据源、模型服务和真实客户材料不因本仓库许可证自动获得授权，使用前仍需分别确认团队授权和数据合规要求。
