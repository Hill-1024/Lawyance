"""
模块描述：预构建大陆法系库索引，供服务端在拉起进程之前把 SQLite 准备好。

在仓库根目录运行：

    .venv/Scripts/python -m RAG.civil_law.scripts.warm_cache

作用与 `services/law_cache.py` 在启动时调用 `ensure_*_database_ready` 相同，
区别是这一步发生在**进程启动之前**——部署时先跑它，服务起来就是复用现成的库
（实测 0.08 秒），不必让第一个请求等整库重建。

幂等：语料没变就什么都不做。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from RAG.civil_law import ensure_civil_law_database_ready  # noqa: E402

MODE_HINT = {
    "reuse": "语料未变，直接复用现成索引",
    "incremental": "只重建了变化的文件",
    "full": "整库重建（首次、语料大改或 schema 升级）",
}


def main() -> int:
    started = time.time()
    info = ensure_civil_law_database_ready()
    elapsed = time.time() - started

    mode = str(info.get("mode", "unknown"))
    print("=" * 66)
    print("大陆法系库索引准备完成")
    print("=" * 66)
    print(f"  模式      {mode}（{MODE_HINT.get(mode, '未知')}）")
    print(f"  耗时      {elapsed:.2f} 秒")
    print(f"  语料文件  {info.get('file_count', 0)} 个")
    print(f"  法律      {info.get('law_count', 0)} 部")
    print(f"  条文      {info.get('article_count', 0)} 条（含质检标记为不可用的）")
    print(f"  索引文件  {info.get('db_path', '')}")
    print(f"  语料指纹  {info.get('content_sha256', '')[:16]}…")
    print(f"  schema    v{info.get('schema_version', '?')}")

    changed = {k: v for k, v in info.items() if k.endswith("_files") and k != "file_count"}
    if changed:
        print(f"  本次变化  {json.dumps(changed, ensure_ascii=False)}")

    if mode == "full" and elapsed > 3:
        print("\n  提示：本次是整库重建。若部署要求进程启动即用，建议在发布流程里"
              "\n        先跑一次本脚本预热，把重建成本挪到发布阶段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
