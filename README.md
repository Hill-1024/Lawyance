# Lawyance

中文 | [English](./README.en.md) | [日本語](./README.ja.md)

Lawyance 是工大法智团队的中文法律 AI 助手项目。它把法律咨询、法条检索、案例匹配、企业信息查询、合同/PDF/Word 文档处理、对话级记忆和前端工作区组织在同一套应用中，目标不是给出无法追溯的“直接结论”，而是把法律问题拆成事实、依据、检索结果和可继续核验的分析路径。

仓库同时包含 FastAPI 后端、React/Vite 前端、工具转发层、法律数据检索客户端、文档处理工具、对话记忆系统和输出审查流程。各模块之间保持清晰边界，业务工具统一通过 `mcps` 暴露给 agent，不在业务层绕过工具中间件。

## 项目定位

- 面向中文法律场景的 AI 助手原型。
- 支持直接回答、ReAct、Plan-and-Solve 等不同复杂度的 agent 工作方式。
- 通过工具调用接入法条、案例、企业信息和文档处理能力。
- 通过对话级记忆保留稳定事实、用户约束和当前工作边界。
- 通过前端工作区管理上传文件、生成文件和对话上下文。

## 核心能力

- **法律检索**: 支持法条精确查询、自然语言法条搜索、来源链接确认和案例匹配。
- **企业信息**: 接入企业概况、上市信息、联系方式、股东、登记信息、主要人员和对外投资等查询能力。
- **文档处理**: 支持 PDF 文本读取、PDF 句级批注、Word 读取和 Word 批注写入。
- **Agent 模式**: 支持默认回答、ReAct 工具行动和 Plan-and-Solve 分步处理。
- **会话工作区**: 为每个用户和对话隔离 `TEMP` 与 `Result` 文件空间，避免文件串线。
- **对话级记忆**: 记录和检索稳定事实、目标、约束与语义标签，不把全部历史暴力塞回上下文。
- **认证与审计**: 包含登录、角色、管理员账号管理、API 访问日志和基础限流。
- **前端体验**: React 19 + Vite，提供对话、文件、工作区、主题、管理员面板和 Lawyance 品牌界面。

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
Default / ReAct / Plan-and-Solve agents
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
| `agent.py` | FastAPI 应用、认证依赖、限流、日志、文件工作区和主要 API |
| `function_calling.py` | 模型调用、工具调用编排和系统记忆入口 |
| `agents/` | 默认、ReAct、Plan-and-Solve agent 实现 |
| `mcps.py` | 业务工具统一转发层 |
| `mcp/` | 法律、企业、PDF、Word、记忆等工具客户端 |
| `memory_system/` | 对话级结构化记忆服务 |
| `RAG/` | 本地法律数据检索相关逻辑 |
| `src/` | React 前端应用 |
| `tests/` | 记忆系统和输出审查流程测试 |

## 环境要求

- Python 3.13 或更高版本。
- Node.js 与 pnpm。
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

## 动态 Prompt

Lawyance 的系统 prompt 已拆分到 `prompts/lawyance/`，后端每次构造对话上下文时都会重新读取这些片段：

- `core/`：身份、硬约束、工具信源规则、输出契约、文件处理规则
- `modes/`：`default`、`react`、`plan_and_solve` 三种 agent 模式的注意力焦点
- `focus/`：按当前请求动态追加的法律检索、文件处理、任务边界焦点
- `tasks/`：历史摘要等内部任务专用 prompt

工具 schema 不放进动态 prompt，也不从 prompt 目录读取；模型工具能力仍由 `function_calling.call()` 中的 `tools=tools` 常态传入。

可选环境变量：

- `LAWYANCE_PROMPT_ROOT`：指定完整 prompt 根目录
- `LAWYANCE_PROMPT_PROFILE`：指定 `prompts/<profile>`，默认 `lawyance`
- `LAWYANCE_PROMPT_INCLUDE_EXAMPLES=1`：将 `examples/` 中的 few-shot 示例追加到系统 prompt

## 对话记忆与 RAG 权重

记忆系统仍以对话级结构化记忆为主，召回时会融合关键词、语义标签、实体、时效、优先级和焦点等多路信号。可选开启 embedding 召回后，向量相似度会作为其中一路 `embedding` 信号进入同一套 RAG 权重排序，而不是替换现有多路召回。

可选环境变量：

- `MEMORY_EMBEDDING_ENABLED=1`：启用 embedding 召回权重，默认关闭
- `EMBEDDING_API_KEY`：embedding 服务 API Key
- `EMBEDDING_BASE_URL`：embedding 服务 OpenAI-compatible Base URL，默认 `https://api.siliconflow.cn/v1`
- `EMBEDDING_MODEL`：embedding 模型，默认 `Qwen/Qwen3-Embedding-8B`
- `MEMORY_EMBEDDING_TIMEOUT`：embedding 请求超时时间，默认 8 秒

## 测试

```bash
python -m pytest
```

当前测试重点覆盖：

- `tests/test_memory_system.py`: 对话级记忆的记录、检索、约束处理和上下文生成。
- `tests/test_ocp.py`: 输出审查流程的格式兜底、完成态和异常场景。

## 开发边界

- `mcps.py` 是业务工具面向 agent 的统一入口。新增工具时应先接入 `mcp/` 客户端，再由 `mcps` 暴露，而不是让 agent 或业务接口直接绕过。
- 记忆系统当前定位是对话级结构化记忆，不是用户级长期画像；可选 embedding 只作为召回权重信号参与排序。
- 上传文件和生成文件必须落在用户/对话隔离的工作区内，避免跨会话读取或写入。
- 法律回答应尽量保留依据链路：事实、法条、案例或来源链接要能被继续核验。
- 前端迁移和 UI 调整应尊重 Lawyance 设计系统，不通过 padding 或临时兼容层掩盖布局问题。

## 安全注意

- `.env`、真实合同、客户材料、生成结果和日志都可能包含敏感信息，不应随意提交。
- 首次部署必须配置 `SECRET_KEY`（至少 32 位随机值）和一次性的 `INITIAL_ADMIN_PASSWORD`；创建 `data/account.json` 后应移除初始密码环境变量。
- 默认 CORS、限流和认证策略适合内部原型阶段，公开部署前需要按实际域名和安全策略收紧。
- 管理员接口具备账号管理和日志读取能力，应只暴露给可信管理员。
- 文件批注、文档读取和下载接口需要持续关注路径隔离和权限边界。

## 许可证

本项目源代码根据 GNU Affero General Public License v3.0（AGPL-3.0）开源，详见 [LICENSE](./LICENSE)。

复用、修改、分发或以网络服务形式对外提供本项目时，请遵守 AGPL-3.0 的条款。业务数据、第三方数据源、模型服务和真实客户材料不因本仓库许可证自动获得授权，使用前仍需分别确认团队授权和数据合规要求。
