#!/usr/bin/env python3
"""
把 RULE_PACKS 中各国实例的 rule_id 挂回共享层原则 JSON 的 country_rule_ids（4.3）。

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.sync_principle_links
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.islamic_law.scripts.insert_riba_sample import (  # noqa: E402
    PRINCIPLE_PACKS,
    build_principle_rule_index,
    load_country_rules,
)


def sync_principle_packs() -> dict[str, int]:
    linked = build_principle_rule_index(load_country_rules())
    counts: dict[str, int] = {}
    for path in PRINCIPLE_PACKS:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            items = [raw]
            as_list = False
        elif isinstance(raw, list):
            items = raw
            as_list = True
        else:
            raise TypeError(f"Unsupported principle pack shape: {path}")
        for item in items:
            pid = item["sharia_principle_id"]
            ids = linked.get(pid, [])
            item["country_rule_ids"] = ids
            counts[pid] = len(ids)
        out = items if as_list else items[0]
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")
    return counts


def main() -> None:
    counts = sync_principle_packs()
    for pid, n in sorted(counts.items()):
        print(f"  {pid}: {n}")
    print("done")


if __name__ == "__main__":
    main()
