"""确保 unittest / 直接导入用例时能找到 backend/ 下的生产模块。"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
for candidate in (_BACKEND, _REPO_ROOT):
    path = str(candidate)
    if path not in sys.path:
        sys.path.insert(0, path)
