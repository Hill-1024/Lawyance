#!/usr/bin/env python3
"""Export the customer application with no law engine, corpus, or host secrets.

Default: export tracked files from the current checkout (including local edits).
--build-context prepares those files and the two tracked Docker build helpers.
--no-git-context consumes only an existing, verified CUSTOMER-MANIFEST.json;
it never discovers additional application files from the filesystem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = frozenset({
    "agent.py", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "pyproject.toml", "uv.lock", "requirements.txt", "tsconfig.json",
    "vite.config.ts", "eslint.config.js", "LICENSE", ".env_example",
})
ROOT_DIRS = frozenset({"backend", "frontend", "assets", "tools"})
DEPLOY_FILES = frozenset({
    "deploy/router/router.py", "deploy/router/maintenance.html",
    "deploy/router/config.example.json", "deploy/docker/compose.customer.yml",
    "deploy/docker/customer.env.example", "deploy/docker/compose.infra.yml",
    "deploy/docker/infra.env.example", "deploy/docker/searxng/settings.yml",
    "deploy/customer/README.md",
})
DENIED_PARTS = frozenset({
    "rag", "law_service", "vector_store", ".git", ".github", ".venv", "venv",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".cache", "cache", "caches", "data", "temp", "result",
    "logs", "log", "releases", "secrets", "keys", ".aws", ".codex", ".agents",
    "build", ".vite", ".next", ".nuxt", ".turbo", ".parcel-cache",
    ".svelte-kit", "coverage", "htmlcov", ".tox", ".nox", ".hypothesis",
})
DENIED_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".log", ".jsonl",
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".zip",
    ".tar", ".gz", ".7z", ".bak", ".backup", ".lock-wal", ".lock-shm",
    ".env", ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm",
    ".sqlite3-wal", ".sqlite3-shm",
})
MANIFEST = "CUSTOMER-MANIFEST.json"
REQUIRED_FILES = frozenset({"agent.py", "package.json", "pyproject.toml", "uv.lock", "backend/app_factory.py"})
BUILD_HELPERS = frozenset({"scripts/package-customer.py", "deploy/docker/Dockerfile"})


def safe_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name or ":" in name:
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        return False
    parts = tuple(part.casefold() for part in path.parts)
    if any(part in DENIED_PARTS for part in parts):
        return False
    base = parts[-1]
    if any(part.startswith(".env") for part in parts) and name != ".env_example":
        return False
    if base in {"keys.json", "secrets.json", "sessions.json", "titles.json"}:
        return False
    if re.search(r"(?:^|[._-])(?:keys?|secrets?|credentials?)(?:[._-]|$)", base):
        return False
    if base.startswith(("audit.", "id_rsa", "id_ed25519")):
        return False
    if PurePosixPath(base).suffix in DENIED_SUFFIXES:
        return False
    return True


def allowed_name(name: str, *, include_dist: bool = False) -> bool:
    if not safe_name(name):
        return False
    path = PurePosixPath(name)
    return (
        name in ROOT_FILES or name in DEPLOY_FILES
        or (len(path.parts) > 1 and path.parts[0] in ROOT_DIRS)
        or (include_dist and len(path.parts) > 1 and path.parts[0] == "dist")
    )


def _git_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True,
    )
    names = [os.fsdecode(raw) for raw in result.stdout.split(b"\0") if raw]
    if any(name.casefold().startswith("rag/data/") for name in names):
        raise ValueError("RAG/data is still tracked; remove corpus from Git before distribution")
    return names


def _regular_path(root: Path, name: str) -> Path:
    path = root / name
    current = root
    for component in PurePosixPath(name).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"Symlink is not allowed in a customer package: {name}")
    if not path.is_file():
        raise ValueError(f"Tracked customer source is missing or not a regular file: {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Customer source escapes the checkout: {name}")
    return path


def select_files(root: Path, *, no_git_context: bool = False, include_dist: bool = False) -> list[str]:
    if no_git_context:
        return sorted(_context_manifest(root, include_dist=include_dist)["files"])
    candidates = _git_files(root)
    if include_dist and (root / "dist").exists():
        candidates.extend(path.relative_to(root).as_posix() for path in (root / "dist").rglob("*") if path.is_file())
    names = sorted({name for name in candidates if allowed_name(name, include_dist=include_dist)})
    for name in names:
        _regular_path(root, name)
    missing = REQUIRED_FILES.difference(names)
    if missing:
        raise ValueError("Missing required customer files: " + ", ".join(sorted(missing)))
    return names


def manifest_for(root: Path, names: list[str]) -> dict:
    return {
        "format": 1,
        "law_source": "remote",
        "files": {name: hashlib.sha256(_regular_path(root, name).read_bytes()).hexdigest() for name in names},
    }


def _source_manifest(root: Path, *, no_git_context: bool = False, include_dist: bool = False) -> dict:
    if no_git_context:
        return _context_manifest(root, include_dist=include_dist)
    return manifest_for(root, select_files(root, include_dist=include_dist))


def export_directory(root: Path, target: Path, *, no_git_context: bool = False, include_dist: bool = False) -> dict:
    manifest = _source_manifest(root, no_git_context=no_git_context, include_dist=include_dist)
    target = target.absolute()
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ValueError("Output directory must be new or empty; refusing to overwrite files")
    if target.resolve() == root.resolve() or root.resolve().is_relative_to(target.resolve()):
        raise ValueError("Output directory cannot contain the source checkout")
    target.mkdir(parents=True, exist_ok=True)
    for name in sorted(manifest["files"]):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_regular_path(root, name), destination)
        destination.chmod(0o644)
    (target / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify_directory(target)
    return manifest


def build_context(root: Path, target: Path) -> dict:
    """Prepare a Git-selected customer context, plus exactly two tracked helpers."""
    tracked = set(_git_files(root))
    missing = BUILD_HELPERS.difference(tracked)
    if missing:
        raise ValueError("Build helpers must be tracked: " + ", ".join(sorted(missing)))
    for name in BUILD_HELPERS:
        _regular_path(root, name)
    manifest = export_directory(root, target)
    for name in sorted(BUILD_HELPERS):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_regular_path(root, name), destination)
        destination.chmod(0o644)
    if _context_manifest(target) != manifest:
        raise ValueError("Prepared build context does not match the customer manifest")
    return manifest


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate customer manifest key: {key}")
        result[key] = value
    return result


def _parse_manifest(raw: bytes, *, include_dist: bool = True) -> dict:
    manifest = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict):
        raise ValueError("Invalid customer manifest")
    expected = manifest.get("files")
    if (type(manifest.get("format")) is not int or manifest["format"] != 1
            or manifest.get("law_source") != "remote" or not isinstance(expected, dict)):
        raise ValueError("Invalid customer manifest")
    for name, checksum in expected.items():
        if not isinstance(name, str) or not allowed_name(name, include_dist=include_dist):
            raise ValueError(f"Forbidden customer manifest member: {name}")
        if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise ValueError(f"Invalid customer manifest checksum: {name}")
    if not REQUIRED_FILES.issubset(expected):
        raise ValueError("Customer package is missing required application files")
    return manifest


def _verify_members(members: dict[str, bytes], *, include_dist: bool = True) -> dict:
    if MANIFEST not in members:
        raise ValueError("Customer manifest is missing")
    manifest = _parse_manifest(members[MANIFEST], include_dist=include_dist)
    for name in members:
        if name != MANIFEST and not allowed_name(name, include_dist=include_dist):
            raise ValueError(f"Forbidden customer package member: {name}")
    expected = manifest["files"]
    if set(expected) != set(members).difference({MANIFEST}):
        raise ValueError("Customer manifest file list does not match the package")
    for name, checksum in expected.items():
        if hashlib.sha256(members[name]).hexdigest() != checksum:
            raise ValueError(f"Customer package checksum mismatch: {name}")
    return manifest


def _directory_members(target: Path, *, allow_build_helpers: bool = False, include_dist: bool = True) -> dict[str, bytes]:
    if target.is_symlink():
        raise ValueError("Symlink is not allowed in a customer package")
    if not (target / MANIFEST).exists():
        raise ValueError("Customer manifest is missing")
    members = {}
    for path in target.rglob("*"):
        name = path.relative_to(target).as_posix()
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in a customer package: {name}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Customer source is not a regular file: {name}")
        if allow_build_helpers and name in BUILD_HELPERS:
            continue
        if name != MANIFEST and not allowed_name(name, include_dist=include_dist):
            raise ValueError(f"Forbidden customer package member: {name}")
        members[name] = path.read_bytes()
    return members


def _context_manifest(root: Path, *, include_dist: bool = False) -> dict:
    # Enumeration verifies the exact manifest set; it cannot select new sources.
    return _verify_members(
        _directory_members(root, allow_build_helpers=True, include_dist=include_dist),
        include_dist=include_dist,
    )


def verify_directory(target: Path) -> dict:
    return _verify_members(_directory_members(target))


def verify_archive(path: Path) -> dict:
    members = {}
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            if item.is_dir():
                if not safe_name(item.filename.rstrip("/")):
                    raise ValueError(f"Unsafe archive directory: {item.filename}")
                continue
            if item.filename in members:
                raise ValueError(f"Duplicate archive member: {item.filename}")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError(f"Symlink archive member: {item.filename}")
            members[item.filename] = archive.read(item)
    return _verify_members(members)


def export_archive(root: Path, target: Path, *, no_git_context: bool = False, include_dist: bool = False) -> dict:
    manifest = _source_manifest(root, no_git_context=no_git_context, include_dist=include_dist)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(manifest["files"]):
            archive.write(_regular_path(root, name), name)
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    verify_archive(target)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output", type=Path, help="Create a new customer .zip archive (never overwrite)")
    output.add_argument("--output-dir", type=Path, help="Export into a new or empty directory")
    output.add_argument("--build-context", type=Path, help="Prepare a tracked customer Docker context with build helpers")
    output.add_argument("--verify", type=Path, help="Verify an exported .zip or directory")
    output.add_argument("--verify-only", action="store_true", help="Check Git corpus boundary and selected files")
    parser.add_argument("--no-git-context", action="store_true", help="Consume an existing verified customer manifest without .git")
    parser.add_argument("--include-dist", action="store_true", help="Include an existing frontend dist (build it from this release first)")
    args = parser.parse_args(argv)
    if args.build_context and (args.no_git_context or args.include_dist):
        parser.error("--build-context requires Git mode and cannot use --include-dist")
    try:
        if args.build_context:
            manifest = build_context(ROOT, args.build_context)
        elif args.verify:
            manifest = verify_directory(args.verify) if args.verify.is_dir() else verify_archive(args.verify)
        elif args.verify_only:
            manifest = _source_manifest(ROOT, no_git_context=args.no_git_context, include_dist=args.include_dist)
        elif args.output_dir:
            manifest = export_directory(ROOT, args.output_dir, no_git_context=args.no_git_context, include_dist=args.include_dist)
        else:
            manifest = export_archive(ROOT, args.output, no_git_context=args.no_git_context, include_dist=args.include_dist)
    except (ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Customer distribution rejected: {exc}\n")
    print(json.dumps({"ok": True, "files": len(manifest["files"]), "law_source": "remote"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
