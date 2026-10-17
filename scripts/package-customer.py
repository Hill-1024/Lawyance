#!/usr/bin/env python3
"""Export the customer application with no law engine, corpus, or host secrets.

Default: export tracked files from the current checkout (including local edits).
--no-git-context is explicitly reserved for the Docker build context, where .git
is absent. Both modes share a narrow allowlist and reject unsafe file names,
symlinks, secret-like artifacts, caches and runtime directories.
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
        # Never recurse into denied subtrees, even for Docker contexts.
        candidates = []
        for directory, children, files in os.walk(root, followlinks=False):
            relative = Path(directory).relative_to(root)
            kept = []
            for child in children:
                child_name = (relative / child).as_posix()
                wanted = (
                    child in ROOT_DIRS or (include_dist and child == "dist")
                    if relative == Path(".") else
                    (allowed_name(child_name, include_dist=include_dist)
                     or any(name.startswith(child_name + "/") for name in DEPLOY_FILES))
                )
                if relative == Path(".") and any(name.startswith(child_name + "/") for name in DEPLOY_FILES):
                    wanted = True
                if not wanted or child.casefold() in DENIED_PARTS:
                    continue
                if (Path(directory) / child).is_symlink():
                    raise ValueError(f"Symlink is not allowed in a customer package: {child_name}")
                kept.append(child)
            children[:] = kept
            candidates.extend((relative / name).as_posix() for name in files)
    else:
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


def export_directory(root: Path, target: Path, *, no_git_context: bool = False, include_dist: bool = False) -> dict:
    names = select_files(root, no_git_context=no_git_context, include_dist=include_dist)
    target = target.absolute()
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ValueError("Output directory must be new or empty; refusing to overwrite files")
    if target.resolve() == root.resolve() or root.resolve().is_relative_to(target.resolve()):
        raise ValueError("Output directory cannot contain the source checkout")
    target.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(root, names)
    for name in names:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_regular_path(root, name), destination)
        destination.chmod(0o644)
    (target / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify_directory(target)
    return manifest


def _verify_members(members: dict[str, bytes], *, include_dist: bool = True) -> dict:
    if MANIFEST not in members:
        raise ValueError("Customer manifest is missing")
    for name in members:
        if name != MANIFEST and not allowed_name(name, include_dist=include_dist):
            raise ValueError(f"Forbidden customer package member: {name}")
    manifest = json.loads(members[MANIFEST])
    expected = manifest.get("files")
    if manifest.get("format") != 1 or manifest.get("law_source") != "remote" or not isinstance(expected, dict):
        raise ValueError("Invalid customer manifest")
    if set(expected) != set(members).difference({MANIFEST}):
        raise ValueError("Customer manifest file list does not match the package")
    if not REQUIRED_FILES.issubset(expected):
        raise ValueError("Customer package is missing required application files")
    for name, checksum in expected.items():
        if hashlib.sha256(members[name]).hexdigest() != checksum:
            raise ValueError(f"Customer package checksum mismatch: {name}")
    return manifest


def verify_directory(target: Path) -> dict:
    members = {}
    for path in target.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in a customer package: {path.name}")
        if path.is_file():
            members[path.relative_to(target).as_posix()] = path.read_bytes()
    return _verify_members(members)


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
    names = select_files(root, no_git_context=no_git_context, include_dist=include_dist)
    manifest = manifest_for(root, names)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(_regular_path(root, name), name)
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    verify_archive(target)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output", type=Path, help="Create a new customer .zip archive (never overwrite)")
    output.add_argument("--output-dir", type=Path, help="Export into a new or empty directory")
    output.add_argument("--verify", type=Path, help="Verify an exported .zip or directory")
    output.add_argument("--verify-only", action="store_true", help="Check Git corpus boundary and selected files")
    parser.add_argument("--no-git-context", action="store_true", help="Docker only: use the safe allowlist without .git")
    parser.add_argument("--include-dist", action="store_true", help="Include an existing frontend dist (build it from this release first)")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            manifest = verify_directory(args.verify) if args.verify.is_dir() else verify_archive(args.verify)
        elif args.verify_only:
            names = select_files(ROOT, no_git_context=args.no_git_context, include_dist=args.include_dist)
            manifest = manifest_for(ROOT, names)
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
