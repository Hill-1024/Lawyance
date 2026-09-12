"""
模块描述：架构边界护栏测试，锁定强解耦不变量与无环依赖图。

不变量（改动架构前请先读 README「调用链与解耦不变量」）：
- I1 只有 mcps.py 与 tools/** 可以 import tools / tools.registry。
- I2 agents/** 不得 import ocp、services、tools、mcp、memory_system、RAG。
- I3 tools/** 不得 import services/**。
- I4 services/**、routes/** 不得 import tools、mcp、memory_system、RAG、ocp。
- I5 生产模块的 import 图无环。

扫描基于 AST，包含函数体内的惰性 import（`if __name__ == "__main__"` 自测块除外），
因为循环依赖往往正是靠惰性 import 掩盖的。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "src",
    "android",
    "ios",
    "tests",
    ".video_agent",
    ".zcode",
    ".omo",
    ".claude",
    ".idea",
    ".vscode",
}

# 能力子系统根：只允许经 mcps 转发，业务层不得直接 import。
CAPABILITY_ROOTS = {"tools", "mcp", "memory_system", "RAG"}

# 范式后处理子系统：只允许 services.ocp_service 直接依赖 ocp。
OCP_MODULE = "ocp"
OCP_ALLOWED_IMPORTERS = {"services.ocp_service"}

# 已知且有意保留的边界例外，附理由；不要为了通过测试而随意扩充。
KNOWN_EXCEPTIONS = {
    # 模型档案是配置存储而非能力子系统；settings_service 也不反向依赖调用方，不构成环。
    ("function_calling", "services.settings_service"),
    ("services.ocp_service", "services.settings_service"),
}


def _iter_python_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in path.relative_to(REPO_ROOT).parts):
            continue
        files.append(path)
    return files


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and any(isinstance(op, ast.Eq) for op in test.ops)
        and any(isinstance(cmp, ast.Constant) and cmp.value == "__main__" for cmp in test.comparators)
    )


class _ImportCollector(ast.NodeVisitor):
    """收集所有 import（含函数体），跳过 __main__ 自测块的引用。"""

    def __init__(self, module: str, package: list[str]):
        self.module = module
        self.package = package
        self.raw: list[tuple[list[str], int, str | None]] = []

    def visit_If(self, node: ast.If):
        if _is_main_guard(node):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.raw.append(([alias.name], 0, None))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        names = [alias.name for alias in node.names]
        if names:
            self.raw.append((names, node.level, node.module))


def _resolve_targets(raw_imports, modules: set[str], package: list[str]) -> set[str]:
    """把 import 语句解析成被依赖的生产模块名集合。"""
    targets: set[str] = set()
    for names, level, module in raw_imports:
        if level and module is None and not names:
            continue
        if level == 0:
            base = module or ""
        else:
            # level=1 指当前包；level=2 再向上一层，以此类推。
            base_parts = package[: len(package) - (level - 1)] if level > 1 else list(package)
            base = ".".join([*base_parts, module] if module else base_parts)
        if not base:
            continue
        for name in names:
            candidate = f"{base}.{name}"
            if candidate in modules:
                targets.add(candidate)
                continue
            # from package import submodule 形式：子模块不一定存在，回退到包本身。
            current = base
            while current and current not in modules:
                current = current.rpartition(".")[0]
            if current:
                targets.add(current)
    return targets


def _imports_by_module() -> dict[str, list[tuple[list[str], int, str | None]]]:
    collected: dict[str, list[tuple[list[str], int, str | None]]] = {}
    for path in _iter_python_files():
        module = _module_name(path)
        if not module:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - 语法错误应先由其它测试暴露
            raise AssertionError(f"无法解析 {path}: {exc}") from exc
        collector = _ImportCollector(module, module.split(".")[:-1])
        collector.visit(tree)
        collected[module] = collector.raw
    return collected


def _resolve_all(imports_by_module) -> dict[str, set[str]]:
    modules = set(imports_by_module)
    return {
        module: _resolve_targets(raw, modules, module.split(".")[:-1])
        for module, raw in imports_by_module.items()
    }


class ArchitectureBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.imports = _imports_by_module()
        cls.graph = _resolve_all(cls.imports)
        cls.modules = set(cls.graph)

    def _edges(self) -> list[tuple[str, str]]:
        return [
            (source, target)
            for source, targets in self.graph.items()
            for target in sorted(targets)
            if (source, target) not in KNOWN_EXCEPTIONS
        ]

    def test_only_mcps_and_tools_may_import_tools_registry(self):
        allowed = {"mcps"} | {m for m in self.modules if m == "tools" or m.startswith("tools.")}
        violations = sorted(
            (source, target)
            for source, target in self._edges()
            if source not in allowed and target in {"tools"} | {m for m in self.modules if m.startswith("tools.")}
        )
        self.assertEqual(violations, [], f"存在绕过 mcps 直连 tools 的模块: {violations}")

    def test_agents_layer_stays_dependency_free(self):
        forbidden = CAPABILITY_ROOTS | {"services", OCP_MODULE}
        violations = []
        for source, target in self._edges():
            if not (source == "agents" or source.startswith("agents.")):
                continue
            if target.split(".")[0] in forbidden:
                violations.append((source, target))
        self.assertEqual(violations, [], f"agents 层出现跨模块直连: {violations}")

    def test_tools_never_import_services(self):
        violations = sorted(
            (source, target)
            for source, target in self._edges()
            if (source == "tools" or source.startswith("tools.")) and target.split(".")[0] == "services"
        )
        self.assertEqual(violations, [], f"tools 层反向依赖 services: {violations}")

    def test_services_and_routes_use_capability_router_only(self):
        forbidden = CAPABILITY_ROOTS | {OCP_MODULE}
        violations = []
        for source, target in self._edges():
            layer = source.split(".")[0]
            if layer not in {"services", "routes"}:
                continue
            if source in OCP_ALLOWED_IMPORTERS and target.split(".")[0] == OCP_MODULE:
                continue
            if target.split(".")[0] in forbidden:
                violations.append((source, target))
        self.assertEqual(violations, [], f"services/routes 绕过核心路由: {violations}")

    def test_production_import_graph_is_acyclic(self):
        # Tarjan SCC：任何大小 > 1 的强连通分量都意味着 import 环。
        index_counter = 0
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        cycles: list[list[str]] = []

        def strongconnect(node: str):
            nonlocal index_counter
            indices[node] = index_counter
            lowlink[node] = index_counter
            index_counter += 1
            stack.append(node)
            on_stack.add(node)

            for neighbour in sorted(self.graph.get(node, ())):
                if neighbour not in indices:
                    strongconnect(neighbour)
                    lowlink[node] = min(lowlink[node], lowlink[neighbour])
                elif neighbour in on_stack:
                    lowlink[node] = min(lowlink[node], indices[neighbour])

            if lowlink[node] == indices[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    cycles.append(sorted(component))

        for module in sorted(self.modules):
            if module not in indices:
                strongconnect(module)

        self.assertEqual(cycles, [], f"生产模块存在 import 环: {cycles}")

    def test_ocp_is_reached_only_through_services_router(self):
        importers = sorted(
            source
            for source, targets in self.graph.items()
            if any(target.split(".")[0] == OCP_MODULE for target in targets)
        )
        self.assertEqual(
            importers,
            sorted(OCP_ALLOWED_IMPORTERS),
            f"OCP 只能由范式路由 services.ocp_service 构造，实际: {importers}",
        )


if __name__ == "__main__":
    unittest.main()
