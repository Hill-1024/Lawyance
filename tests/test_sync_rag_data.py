"""Exercise the Bash synchronizer only in disposable projects, never real RAG/data."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync-rag-data.sh"
COUNT = 5237
PAYLOAD = b'{"fixture": true}\n'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def bash_path(path: Path) -> str:
    # Preserve aliases so the script, rather than this helper, rejects symlinks.
    value = path.absolute().as_posix()
    if os.name == "nt":
        return "/" + value[0].lower() + value[2:]
    return value


def find_bash() -> str | None:
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).parent.parent / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
        return None  # Do not accidentally launch Windows' WSL bash.exe.
    return shutil.which("bash")


BASH = find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="Git Bash or Linux Bash required")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "isolated-project"
    root.mkdir()
    # All script mutations, including rename/rollback, stay inside this fixture.
    assert root.resolve().is_relative_to(tmp_path.resolve())
    assert not SCRIPT.resolve().is_relative_to(root.resolve())
    (root / "scripts").mkdir()
    shutil.copyfile(SCRIPT, root / "scripts" / SCRIPT.name)
    (root / "RAG" / "data").mkdir(parents=True)
    (root / "RAG" / "data" / "old.json").write_bytes(b"old corpus")
    return root


@pytest.fixture(scope="module")
def valid_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("private-data-fixture")
    directory = root / "fixture records"
    directory.mkdir()
    # Hardlinks keep this 5237-file fixture cheap. The export must contain bytes,
    # rather than hardlink members that could refer outside the candidate.
    # Limit each group so a copied fixture also fits NTFS' hardlink limit.
    for number in range(COUNT):
        path = directory / f"{number:04d}.json"
        if number % 256 == 0:
            path.write_bytes(PAYLOAD)
            first = path
        else:
            os.link(first, path)
    (root / "manifest.sha256").write_text(
        "".join(f"{DIGEST}  ./fixture records/{number:04d}.json\n" for number in range(COUNT)),
        encoding="utf-8", newline="\n",
    )
    (root / "README.md").write_text("private data instructions", encoding="utf-8")
    (root / "unlisted-private-file.txt").write_text("not corpus", encoding="utf-8")
    return root


def run_sync(project, source, *arguments, extra_env=None):
    environment = os.environ.copy()
    # Never inherit real private repository settings from the caller.
    for name in ("LAWVER_RAG_DATA_REPO", "LAWVER_RAG_DATA_REF", "LAWVER_RAG_DATA_DIR", "TEST_BIN"):
        environment.pop(name, None)
    environment["LAWVER_RAG_DATA_DIR"] = bash_path(source)
    environment.update(extra_env or {})
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-c",
         'export PATH="${TEST_BIN:+$TEST_BIN:}$PATH"; exec "$BASH" "$@"',
         "isolated-sync-test", bash_path(project / "scripts" / SCRIPT.name), *arguments],
        cwd=project, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90,
    )


def assert_original_intact(project):
    assert (project / "RAG" / "data" / "old.json").read_bytes() == b"old corpus"
    assert not list((project / "RAG").glob("data.backup.*"))
    assert not list((project / "RAG").glob(".data-sync.*"))


def test_success_exports_only_manifest_files_and_retains_backup(project, valid_source):
    result = run_sync(project, valid_source, "fixture-release")
    assert result.returncode == 0, result.stderr
    destination = project / "RAG" / "data"
    files = [path for path in destination.rglob("*") if path.is_file()]
    assert len(files) == COUNT
    assert all(path.read_bytes() == PAYLOAD for path in files)
    assert not (destination / "unlisted-private-file.txt").exists()
    backups = list((project / "RAG").glob("data.backup.*"))
    assert len(backups) == 1
    assert (backups[0] / "old.json").read_bytes() == b"old corpus"
    assert backups[0].name in result.stdout
    assert "fixture-release" in result.stdout
    assert not list((project / "RAG").glob(".data-sync.*"))


def test_checksum_failure_does_not_replace_existing_corpus(project, valid_source, tmp_path):
    source = tmp_path / "bad-checksum"
    shutil.copytree(valid_source, source, copy_function=os.link)
    manifest = source / "manifest.sha256"
    contents = manifest.read_text(encoding="utf-8").replace(DIGEST, "0" * 64, 1)
    manifest.unlink()  # Do not modify the shared fixture through its hardlink.
    manifest.write_text(contents, encoding="utf-8", newline="\n")
    result = run_sync(project, source)
    assert result.returncode != 0
    assert_original_intact(project)


@pytest.mark.parametrize("relationship", ["same", "ancestor", "descendant"])
def test_overlapping_source_and_destination_are_rejected(project, relationship):
    destination = project / "RAG" / "data"
    source = {"same": destination, "ancestor": project, "descendant": destination / "nested"}[relationship]
    source.mkdir(exist_ok=True)
    result = run_sync(project, source)
    assert result.returncode != 0
    assert "互相包含" in result.stderr
    assert_original_intact(project)


@pytest.mark.parametrize("name", ["../outside.json", "/absolute.json", "a/../../outside.json", "a\\outside.json", "a//outside.json", ".git/config"])
def test_manifest_path_traversal_is_rejected_before_replacement(project, tmp_path, name):
    source = tmp_path / "unsafe-manifest"
    source.mkdir()
    (source / "manifest.sha256").write_text(f"{DIGEST}  {name}\n", encoding="utf-8")
    result = run_sync(project, source)
    assert result.returncode != 0
    assert "危险路径" in result.stderr
    assert_original_intact(project)


def test_incomplete_manifest_is_rejected_before_replacement(project, tmp_path):
    source = tmp_path / "incomplete"
    source.mkdir()
    (source / "one.json").write_bytes(PAYLOAD)
    (source / "manifest.sha256").write_text(f"{DIGEST}  one.json\n", encoding="utf-8")
    result = run_sync(project, source)
    assert result.returncode != 0
    assert "期望 5237" in result.stderr
    assert_original_intact(project)


@pytest.mark.parametrize("where", ["source-root", "source-file", "target-root", "target-file"])
def test_symlinks_are_rejected_without_replacing_data(project, tmp_path, where):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"outside untouched")
    try:
        if where == "source-root":
            alias = tmp_path / "source-alias"
            alias.symlink_to(source, target_is_directory=True)
            source = alias
        elif where == "source-file":
            (source / "link").symlink_to(outside, target_is_directory=True)
        elif where == "target-root":
            (project / "RAG" / "data").rename(project / "RAG" / "original-data")
            (project / "RAG" / "data").symlink_to(outside, target_is_directory=True)
        else:
            (project / "RAG" / "data" / "link").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"native symlink creation unavailable: {error}")
    result = run_sync(project, source)
    assert result.returncode != 0
    assert "符号链接" in result.stderr
    assert (outside / "sentinel").read_bytes() == b"outside untouched"
    if where != "target-root":
        assert_original_intact(project)
    else:
        assert (project / "RAG" / "original-data" / "old.json").read_bytes() == b"old corpus"


def test_failed_final_rename_restores_backup(project, valid_source, tmp_path):
    executables = tmp_path / "bin"
    executables.mkdir()
    (executables / "mv").write_text(
        '#!/usr/bin/env bash\n'
        'if [[ "$3" == */candidate ]]; then exit 73; fi\n'
        'exec /usr/bin/mv "$@"\n',
        encoding="utf-8", newline="\n",
    )
    (executables / "mv").chmod(0o755)
    result = run_sync(project, valid_source, extra_env={"TEST_BIN": bash_path(executables)})
    assert result.returncode == 73, result.stderr
    assert "已恢复" in result.stderr
    assert_original_intact(project)
