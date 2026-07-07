#!/usr/bin/env python3
"""
Rename law corpus JSON files to deterministic fixed-length hashes.

The legal title stays in each JSON payload as law_name. The previous filename is
stored as original_filename so the source name remains auditable after the path
is shortened for Git and sync clients.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "RAG" / "data"
HASH_LENGTH = 32
HASH_NAMESPACE = "lawver-law-data-v1"


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path
    source_id: str
    original_filename: str
    law_name: str


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def stable_source_id(category_path: str, original_filename: str, payload: dict[str, Any]) -> str:
    law_name = str(payload.get("law_name") or "").strip()
    url = str(payload.get("url") or "").strip()
    cli = str(payload.get("cli") or "").strip()
    identity = "\0".join(
        [
            HASH_NAMESPACE,
            category_path,
            original_filename,
            url,
            cli,
            law_name,
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:HASH_LENGTH]


def iter_law_json_files(data_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in data_dir.rglob("*.json")
        if path.name != "index.json" and path.is_file()
    )


def build_rename_plan(data_dir: Path) -> list[RenamePlan]:
    plans: list[RenamePlan] = []
    targets: dict[Path, Path] = {}

    for source in iter_law_json_files(data_dir):
        payload = load_json(source)
        original_filename = str(payload.get("original_filename") or source.name).strip()
        if not original_filename:
            original_filename = source.name
        category_path = source.parent.relative_to(data_dir).as_posix()
        source_id = str(payload.get("source_id") or "").strip()
        expected_source_id = stable_source_id(category_path, original_filename, payload)
        if source_id and source_id != expected_source_id:
            expected_source_id = source_id

        target = source.with_name(f"{expected_source_id}{source.suffix.lower()}")
        previous_source = targets.get(target)
        if previous_source is not None and previous_source != source:
            raise RuntimeError(f"hash collision: {previous_source} and {source} -> {target}")
        targets[target] = source

        plans.append(
            RenamePlan(
                source=source,
                target=target,
                source_id=expected_source_id,
                original_filename=original_filename,
                law_name=str(payload.get("law_name") or "").strip(),
            )
        )

    return plans


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def update_law_payloads(plans: list[RenamePlan]) -> None:
    for plan in plans:
        payload = load_json(plan.source)
        changed = False
        if payload.get("source_id") != plan.source_id:
            payload["source_id"] = plan.source_id
            changed = True
        if payload.get("original_filename") != plan.original_filename:
            payload["original_filename"] = plan.original_filename
            changed = True
        if changed:
            write_json(plan.source, payload)


def rename_files(plans: list[RenamePlan]) -> int:
    renamed = 0
    for plan in plans:
        if plan.source == plan.target:
            continue
        if plan.target.exists():
            raise FileExistsError(f"target already exists: {plan.target}")
        plan.source.rename(plan.target)
        renamed += 1
    return renamed


def update_category_indexes(data_dir: Path, plans: list[RenamePlan]) -> int:
    by_original: dict[tuple[Path, str], RenamePlan] = {
        (plan.target.parent, plan.original_filename): plan for plan in plans
    }
    updated = 0

    for index_path in sorted(data_dir.rglob("index.json")):
        payload = load_json(index_path)
        changed = False
        for value in payload.values():
            if not isinstance(value, dict):
                continue
            file_name = str(value.get("file") or "").strip()
            plan = by_original.get((index_path.parent, file_name))
            if plan is None:
                continue
            target_name = plan.target.name
            if value.get("file") != target_name:
                value["file"] = target_name
                value["original_filename"] = plan.original_filename
                value["source_id"] = plan.source_id
                changed = True
        if changed:
            write_json(index_path, payload)
            updated += 1

    return updated


def max_path_length(data_dir: Path) -> int:
    return max(
        (len(path.as_posix().encode("utf-8")) for path in data_dir.rglob("*") if path.is_file()),
        default=0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--write", action="store_true", help="apply the rename")
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    plans = build_rename_plan(data_dir)
    rename_count = sum(1 for plan in plans if plan.source != plan.target)

    print(f"law files: {len(plans)}")
    print(f"files needing rename: {rename_count}")
    print(f"current max path length: {max_path_length(data_dir)}")

    if not args.write:
        print("dry run only; pass --write to apply")
        return 0

    update_law_payloads(plans)
    renamed = rename_files(plans)
    updated_indexes = update_category_indexes(data_dir, build_rename_plan(data_dir))

    print(f"renamed files: {renamed}")
    print(f"updated index files: {updated_indexes}")
    print(f"new max path length: {max_path_length(data_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
