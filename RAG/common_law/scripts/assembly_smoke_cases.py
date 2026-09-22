"""普通法系包的对接冒烟：先缅甸，再新加坡。退出码 0 表示两边都通过。"""

from __future__ import annotations

from RAG.common_law.scripts.smoke_myanmar import main as smoke_myanmar
from RAG.common_law.scripts.smoke_singapore import main as smoke_singapore


def main() -> int:
    code = smoke_myanmar()
    if code not in (0, None):
        return int(code)
    smoke_singapore()
    print("COMMON_LAW ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
