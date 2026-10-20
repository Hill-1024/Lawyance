# Issue #13 审查修复的本地汇总验收

受测分支：`fix/issue-13-review-gates`。基线为
`87b782851839e2a54b295d37f0143850e72d04a4`，受测代码为
`7cc19ee0af1abab784c01b1f8d3cc18ac6930158`。
本记录后的纯文档提交不改变受测实现。以下是本地代码与分发验证，不表示 Linux
服务已发布、客户镜像已构建或生产验收完成。

## 修复与提交

| 审查项 | 最终行为 | 提交 |
| --- | --- | --- |
| 当前版本仍跟踪语料 | 取消 `RAG/data/` 跟踪，补回按私有 manifest 校验的同步流程；不重写旧 Git 历史 | `74f41ab` |
| 客户构建可能带入未跟踪源码 | 从 Git 跟踪清单准备独立上下文；无 Git 导出验证已有 manifest、哈希及完整成员集合 | `f7d47d2` |
| 法库 Bearer 请求继承环境代理 | 法库客户端独立 Session 设置 `trust_env=False`，保留 TLS 校验；准备脚本通过真实三工具探测 | `590aae7` |
| 配置先切换、恢复记录后写 | 完整 `preparing` 恢复记录落盘后才替换配置；成功发布 `prepared`，失败恢复或保留现场阻止重跑 | `1b4b0b9` |
| 审计 IP 可能被误认客户地址 | 明确字段是 TCP 直连对端；客户用量按 key，真实来源另查可信入口日志，不信任请求转发头 | `7cc19ee` |
| 健康探测污染审计与用量报告 | 精确 `/healthz` 免用量审计；汇总过滤历史有效健康行；鉴权 meta 和业务端点保留审计及故障门禁 | `7cc19ee` |

## 回归结果与环境

环境为 Windows、Git Bash、Python 3.13.12。复用既有测试环境，缺失依赖仅安装到
忽略的临时目录；新增 Markdown 与向量测试依赖均按 `uv.lock` 的版本和 wheel 哈希
校验，没有更新项目依赖或原有虚拟环境。

28 个测试文件的初次组合回归为 **343 passed、64 subtests passed、6 failed、6 errors**。
5 项 Word 导出失败来自测试环境缺少 `markdown-it-py`，1 项向量检索失败来自缺少
`qdrant-client`；6 项架构检查错误来自工作区 `TEMP/` 内故意构造的非法 Python
样本被全树 AST 扫描读入。不能将首次运行表述为全部通过。

补齐测试依赖或使用同一 SHA 的干净源码归档后，分别复验：

- Word 导出：**8 passed**。
- 架构边界：**6 passed**；原测试未修改，`git archive` 不含工作区临时样本。
- 向量检索：**15 passed**。

首次未通过的 12 项均已有通过的复验证据；连同原通过项，本轮范围共 355 项测试、
64 个子测试最终通过。该统计包含上述分批复跑，不表示首次组合运行全部通过。

两个新增 shell 脚本的 `bash -n` 均通过；`uv lock --check --offline` 通过，
解析 97 个包。未改前端源码或前端锁文件，本轮没有重跑前端生产构建。
这不是全项目所有测试或全部依赖重新安装的声明。

## 真实客户导出与构建上下文

除了合成样本单测，还对受测检出执行实际 CLI：

| 检查 | 结果 |
| --- | --- |
| `git ls-files -- RAG/data` / 本地保留语料 | 0 个跟踪文件 / 磁盘保留 5237 个文件 |
| 默认客户 ZIP | 299 个客户文件，含 manifest 共 300 个成员 |
| `--build-context` | 302 个文件：299 个客户文件、manifest、2 个构建辅助文件 |
| 无 `.git` 上下文 | `--verify-only`、目录及 ZIP 二次导出、最终交付物验证均通过；辅助文件不进入交付物 |
| 上下文追加源码或篡改内容 | 3 项均拒绝，未生成交付目标 |
| 临时 Git 仓库的未跟踪源码 | `backend/private.py` 与 `frontend/src/private_token.ts` 均未进入上下文或 ZIP |

测试前后主检出的 Git index 与工作区状态一致。上述文件数对应受测代码，后续合法
应用源码变化可改变数量；安全断言是文件集合、哈希与敏感内容排除规则。

## 在干净检出中复跑

使用项目锁定依赖；测试临时目录应位于源码检出之外，避免全树架构检查扫描合成样本。
不要把真实服务器配置或语料当作故障注入样本。
命令包含 `test_law_data_search.py` 的真实语料布局检查。本轮使用本地保留的语料；
全新检出仅在获授权的开发/自营环境按 [RAG/README.md](../RAG/README.md) 同步批准
语料后运行该完整范围。客户环境不得为复跑测试同步私有语料。

```bash
PYTHONPATH=backend:. uv run --frozen --group dev python -m pytest -q \
  tests/test_agent_resource_guards.py tests/test_control_plane_tools.py \
  tests/test_workbench.py tests/test_workbench_conversation_export.py \
  tests/test_law_service.py tests/test_law_service_client.py \
  tests/test_law_service_e2e.py tests/test_law_service_ops.py \
  tests/test_law_service_distribution.py tests/test_law_remote_boundaries.py \
  tests/test_law_remote_routing.py tests/test_prepare_law_remote.py \
  tests/test_prepare_law_remote_transaction.py tests/test_law_service_proxy.py \
  tests/test_customer_build_entrypoint.py tests/test_sync_rag_data.py \
  tests/test_pkulaw_mcp.py tests/test_law_cache_startup.py \
  tests/test_law_data_search.py tests/test_vector_store.py \
  tests/test_progressive_tools.py tests/test_tool_result_compression.py \
  tests/test_tool_schema_compatibility.py tests/test_architecture_boundaries.py \
  tests/test_mcps_workspace_paths.py tests/test_ocp.py \
  tests/test_tool_schema_stability.py tests/test_release_distribution.py

bash -n scripts/sync-rag-data.sh
bash -n deploy/docker/build-customer.sh
uv lock --check --offline
```

## Linux 与发布前仍需完成

- 记录同一完整 SHA、主站源码版本和独立服务 `current` 对应 release；旧版本的验收
  不能替代本次验收，`git pull` 也不会发布独立服务的代码副本。
- 更新仍跟踪语料的旧检出前，核实独立数据副本及备份。Git 更新可能删除原先跟踪的
  `RAG/data/` 文件；本机执行 `git rm --cached` 保留磁盘文件不能证明其它检出也会保留。
- 在隔离候选目录验证数据同步与配置事务，复验 Linux 的 uid/gid/mode、文件及目录
  fsync、失败恢复和中断后 `preparing` 状态；不在生产配置上注入故障。
- 实际使用 BuildKit 构建 customer 与 runtime，检查最终客户镜像边界、非 root 运行、
  remote 模式以及应用启动、空库、登录和真实对话。本地没有 Docker，未执行真实镜像构建。
- 在部署网络环境复验回环与独立 HTTPS 的三工具直连、TLS、健康免审计、业务和鉴权
  meta 的审计故障门禁、双探针及历史健康行过滤。
- 独立服务宣称的 Python 3.10 最低版本兼容性仍需用本次代码验证；本轮仅使用 3.13。
- 按[部署验收清单](issue-13-validation.md)完成实际环境验收；本记录不改变此前暂缓的
  生产恢复或真实通知演练安排。
