# Issue #13 分支验证与集成记录

功能分支：`feat/issue-13-law-service`。
集成基线：dev `4bbe100670c68568e03f9c71c23986048b173516`。
main 发布基线：`af9952839305c8289373eb7b35a2ce9b0c124644`。

## 功能分支验证

Python 3.13 回归：**263 passed，51 subtests passed**。
覆盖独立 API、鉴权/限流/审计、客户端/远程路由、合成语料真实 HTTP 对照、
无本地检索引擎的客户应用生命周期、打包与配置准备工具、工作台、Word 导出和现有工具回归。
测试使用既有 Python 3.13 环境与隔离安装的测试依赖，结果日志留在本地忽略目录。

锁文件检查 `uv lock --check --offline` 和 `pnpm exec vite build` 通过。
最新 dev 的 Word 导出新增依赖尚未入锁，本次单独补齐 Markdown 依赖条目，保留既有依赖版本。

## dev 集成与 main 发布验证

功能分支经 [PR #23](https://github.com/Hill-1024/Lawyance/pull/23) 合入 dev。
在实际合并提交 `87b782851839e2a54b295d37f0143850e72d04a4` 上，
独立服务 E2E、远程边界/路由、工作台、Word 导出与配置准备工具复验：**69 passed**。

main 发布分支只移植本 Issue 的三个功能提交。其 Python 3.13 回归：
**255 passed，51 subtests passed**；依赖锁检查与前端生产构建通过。
此分支不包含 dev 的 Word 导出及其依赖锁补齐，因此测试范围相应去掉 Word 导出测试。

使用项目依赖复跑 main 发布分支测试范围：

```bash
PYTHONPATH=backend:. uv run --frozen --group dev python -m pytest -q \
  tests/test_agent_resource_guards.py tests/test_control_plane_tools.py \
  tests/test_workbench.py \
  tests/test_law_service.py tests/test_law_service_client.py \
  tests/test_law_service_e2e.py tests/test_law_service_ops.py \
  tests/test_law_service_distribution.py tests/test_law_remote_boundaries.py \
  tests/test_law_remote_routing.py tests/test_prepare_law_remote.py \
  tests/test_pkulaw_mcp.py tests/test_law_cache_startup.py \
  tests/test_vector_store.py tests/test_progressive_tools.py \
  tests/test_tool_result_compression.py tests/test_tool_schema_compatibility.py \
  tests/test_architecture_boundaries.py tests/test_mcps_workspace_paths.py \
  tests/test_ocp.py tests/test_tool_schema_stability.py
```

## 提交与集成顺序

功能分支测试并合入 dev、完成初步 E2E 后，以一个 PR 合入 main。
该 PR 保留三条功能提交，便于逐条审阅：

1. 独立服务：标准库 API、配置化检索路径、鉴权/限流/审计与测试。
2. 远程模式：HTTP 客户端、三工具适配、绕过本地混合检索与隔离回归。
3. 部署分发：客户包/镜像边界、systemd/Compose、运维与配置准备工具、通用文档。

向 main 的 PR 只包含本 Issue 的变更；Word 导出及其依赖锁由对应功能发布流程维护。
PR 使用 `Refs #13` 关联任务，后续验收项见 [验收清单](issue-13-validation.md)。

具体环境的执行记录留在本地；公开文档采用模板路径和占位值。Git 合并与运行环境部署分别执行。
