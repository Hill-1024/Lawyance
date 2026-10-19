"""Customer exports cannot carry our law assets, host secrets or runtime state."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_customer", ROOT / "scripts/package-customer.py")
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    contents = {
        "agent.py": "print('application')\n",
        "package.json": '{"appConfig":{"port":3010}}',
        "pyproject.toml": '[project]\nname="fixture"\n',
        "uv.lock": "version = 1\n",
        "backend/app_factory.py": "# application\n",
        "backend/services/law_cache.py": "# remote mode skips local preparation\n",
        "backend/mcp/law_service_client.py": "# remote adapter\n",
        "backend/vector_store/__init__.py": "# proprietary vector engine\n",
        "backend/vector_store/retrieval.py": "# hybrid corpus retrieval\n",
        "backend/vector_store/config.py": "# corpus index configuration\n",
        "tools/__init__.py": "# tools\n",
        ".env_example": "LAWVER_LAW_SERVICE_KEY=\n",
        "deploy/customer/README.md": "customer instructions\n",
        "deploy/docker/compose.customer.yml": "services: {}\n",
        "deploy/router/router.py": "# router\n",
        "frontend/src/app.tsx": "// frontend\n",
        "RAG/law_data_search.py": "# proprietary engine\n",
        "law_service/server.py": "# private service\n",
        "deploy/law-service/keys.example.json": '{"keys":[]}',
        "docs/law-service-split-plan.md": "private deployment plan\n",
        "backend/data/session.json": "private session\n",
        "backend/logs/access.log": "private query\n",
        "backend/private.env": "PRIVATE_TOKEN=secret\n",
        "backend/config/customer.keys.json": '{"key":"private"}',
        "backend/config/credentials.local.json": '{"token":"private"}',
        "backend/cache/index.json": "cached corpus\n",
        "backend/local.sqlite3-wal": "database changes\n",
        "frontend/node_modules/private/index.js": "private dependency\n",
        "frontend/src/.env.production": "PRIVATE_KEY=secret\n",
        "frontend/src/private.pem": "private key\n",
        "scripts/law_service_ops.py": "# private operator\n",
        "data/memory.sqlite3": "private memory\n",
        ".env": "REAL_KEY=secret\n",
        "keys.json": '{"keys":["private"]}',
        "audit.jsonl": "private audit\n",
    }
    for name, content in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if shutil.which("git"):
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    return root


@pytest.mark.parametrize("no_git_context", [False, True])
def test_export_excludes_corpus_engine_secrets_and_state(source, tmp_path, no_git_context):
    if not no_git_context and not shutil.which("git"):
        pytest.skip("git is required for the default publishing mode")
    # An ignored/untracked corpus must never enter either export mode.
    raw = source / "RAG/data/private-law.json"
    raw.parent.mkdir()
    raw.write_text("PRIVATE CORPUS", encoding="utf-8")
    target = tmp_path / "customer"
    manifest = packager.export_directory(source, target, no_git_context=no_git_context)
    exported = set(manifest["files"])
    assert "backend/mcp/law_service_client.py" in exported
    assert "deploy/customer/README.md" in exported
    assert ".env_example" in exported
    assert (target / "package.json").read_bytes() == (source / "package.json").read_bytes()
    assert not (target / "RAG").exists()
    assert not (target / "law_service").exists()
    assert not (target / "backend/vector_store").exists()
    assert not (target / ".git").exists()
    assert exported == {
        "agent.py", "package.json", "pyproject.toml", "uv.lock", ".env_example",
        "backend/app_factory.py", "backend/services/law_cache.py",
        "backend/mcp/law_service_client.py", "tools/__init__.py",
        "deploy/customer/README.md", "deploy/docker/compose.customer.yml",
        "deploy/router/router.py", "frontend/src/app.tsx",
    }
    assert packager.verify_directory(target) == manifest
    assert raw.read_text(encoding="utf-8") == "PRIVATE CORPUS"


def test_default_mode_rejects_tracked_corpus(source):
    if not shutil.which("git"):
        pytest.skip("git is required")
    raw = source / "RAG/data/private-law.json"
    raw.parent.mkdir()
    raw.write_text("PRIVATE CORPUS", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RAG/data"], check=True)
    with pytest.raises(ValueError, match="still tracked"):
        packager.select_files(source)


def test_archive_round_trip_and_tampering_are_detected(source, tmp_path):
    archive = tmp_path / "customer.zip"
    manifest = packager.export_archive(source, archive, no_git_context=True)
    assert packager.verify_archive(archive) == manifest
    with pytest.raises(FileExistsError):
        packager.export_archive(source, archive, no_git_context=True)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("RAG/data/leaked.json", "PRIVATE CORPUS")
    with pytest.raises(ValueError, match="Forbidden|file list"):
        packager.verify_archive(archive)


def test_export_does_not_overwrite_existing_files(source, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    original = target / "important.txt"
    original.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty"):
        packager.export_directory(source, target, no_git_context=True)
    assert original.read_text(encoding="utf-8") == "keep"


def test_manifest_integrity_and_unlisted_files_are_checked(source, tmp_path):
    target = tmp_path / "customer"
    packager.export_directory(source, target, no_git_context=True)
    (target / "agent.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        packager.verify_directory(target)
    (target / "backend/injected.py").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="file list"):
        packager.verify_directory(target)


@pytest.mark.parametrize("entry", ["../agent.py", "/absolute.py", "backend\\escape.py", "backend/cache/entry.json", "backend/config/new.key", "backend/.git/config", "backend/.env/config.json", "backend/vector_store/retrieval.py", "backend/VECTOR_STORE/config.py"])
def test_archive_verification_rejects_unsafe_member_names(source, tmp_path, entry):
    archive = tmp_path / "customer.zip"
    packager.export_archive(source, archive, no_git_context=True)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr(entry, "unsafe")
    # ZipInfo normalizes Windows backslashes; either unsafe-name or manifest
    # rejection must still stop distribution on that platform.
    with pytest.raises(ValueError, match="Forbidden|file list"):
        packager.verify_archive(archive)


def test_archive_symlink_member_is_rejected(source, tmp_path):
    archive = tmp_path / "customer.zip"
    packager.export_archive(source, archive, no_git_context=True)
    with zipfile.ZipFile(archive, "a") as output:
        info = zipfile.ZipInfo("backend/link.py")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(info, "../../keys.json")
    with pytest.raises(ValueError, match="Symlink"):
        packager.verify_archive(archive)


def test_customer_source_symlink_is_rejected(source, tmp_path):
    target = source / "backend/linked.py"
    try:
        target.symlink_to(source / "RAG/law_data_search.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable for this host account")
    with pytest.raises(ValueError, match="Symlink"):
        packager.export_directory(source, tmp_path / "customer", no_git_context=True)


def test_existing_dist_requires_explicit_opt_in(source, tmp_path):
    (source / "dist").mkdir()
    (source / "dist/index.html").write_text("<html></html>", encoding="utf-8")
    (source / "dist/.env").write_text("PRIVATE", encoding="utf-8")
    assert "dist/index.html" not in packager.select_files(source, no_git_context=True)
    names = packager.select_files(source, no_git_context=True, include_dist=True)
    assert "dist/index.html" in names
    assert "dist/.env" not in names


def test_deployment_templates_keep_customer_and_first_party_separate():
    compose = (ROOT / "deploy/docker/compose.customer.yml").read_text(encoding="utf-8")
    assert "PORT: '8081'" in compose
    assert "LAWVER_LAW_SOURCE: remote" in compose
    assert "LAWVER_LAW_SERVICE_URL:" in compose
    assert ":/app/RAG" not in compose
    assert "LAWVER_CUSTOMER_IMAGE:?" in compose
    service_compose = (ROOT / "deploy/docker/compose.law-service.yml").read_text(encoding="utf-8")
    assert "'127.0.0.1:${LAW_PUBLISH_PORT:-8084}:8084'" in service_compose
    assert "create_host_path: false" in service_compose
    assert "read_only: true" in service_compose
    systemd = (ROOT / "deploy/systemd/lawver-law.service").read_text(encoding="utf-8")
    assert " -m law_service" in systemd
    assert "ReadWritePaths=/var/lib/lawver-law" in systemd
    dockerfile = (ROOT / "deploy/docker/Dockerfile.law-service").read_text(encoding="utf-8")
    assert "COPY RAG/law_data_search.py" in dockerfile
    assert "COPY RAG/ " not in dockerfile
