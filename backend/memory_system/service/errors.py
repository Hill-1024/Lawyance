from __future__ import annotations

from typing import Any

class MemoryRevisionConflict(Exception):
    def __init__(self, expected_revision: int, actual_revision: int, snapshot: dict[str, Any]):
        super().__init__("memory revision conflict")
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        self.snapshot = snapshot

__all__ = [name for name in globals() if not name.startswith("__")]
