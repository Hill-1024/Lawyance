"""Customer exports cannot carry our law assets, host secrets or runtime state."""
from __future__ import annotations

import importlib.util
import json
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
    if not shutil.which("git"):
        pytest.skip("git is required to prepare a trusted customer manifest")
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
        "scripts/package-customer.py": "# tracked packaging helper\n",
        "deploy/docker/Dockerfile": "# tracked Docker helper\n",
        "data/memory.sqlite3": "private memory\n",
        ".env": "REAL_KEY=secret\n",
        "keys.json": '{"keys":["private"]}',
        "audit.jsonl": "private audit\n",
    }
    for name, content in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    return root


@pytest.fixture
def context(source, tmp_path):
    target = tmp_path / "prepared-context"
    packager.build_context(source, target)
    return target


@pytest.mark.parametrize("no_git_context", [False, True])
def test_export_excludes_corpus_engine_secrets_and_state(source, tmp_path, no_git_context):
    if not no_git_context and not shutil.which("git"):
        pytest.skip("git is required for the default publishing mode")
    # An ignored/untracked corpus must never enter either export mode.
    raw = source / "RAG/data/private-law.json"
    raw.parent.mkdir()
    raw.write_text("PRIVATE CORPUS", encoding="utf-8")
    target = tmp_path / "customer"
    input_root = source
    if no_git_context:
        input_root = tmp_path / "prepared-context"
        packager.build_context(source, input_root)
    manifest = packager.export_directory(input_root, target, no_git_context=no_git_context)
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


def test_default_mode_rejects_tracked_corpus(source, tmp_path):
    if not shutil.which("git"):
        pytest.skip("git is required")
    raw = source / "RAG/data/private-law.json"
    raw.parent.mkdir()
    raw.write_text("PRIVATE CORPUS", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RAG/data"], check=True)
    with pytest.raises(ValueError, match="still tracked"):
        packager.select_files(source)
    with pytest.raises(ValueError, match="still tracked"):
        packager.build_context(source, tmp_path / "context")


def test_archive_round_trip_and_tampering_are_detected(context, tmp_path):
    archive = tmp_path / "customer.zip"
    manifest = packager.export_archive(context, archive, no_git_context=True)
    assert packager.verify_archive(archive) == manifest
    with pytest.raises(FileExistsError):
        packager.export_archive(context, archive, no_git_context=True)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("RAG/data/leaked.json", "PRIVATE CORPUS")
    with pytest.raises(ValueError, match="Forbidden|file list"):
        packager.verify_archive(archive)


def test_export_does_not_overwrite_existing_files(context, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    original = target / "important.txt"
    original.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty"):
        packager.export_directory(context, target, no_git_context=True)
    assert original.read_text(encoding="utf-8") == "keep"


def test_manifest_integrity_and_unlisted_files_are_checked(context, tmp_path):
    target = tmp_path / "customer"
    packager.export_directory(context, target, no_git_context=True)
    (target / "agent.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        packager.verify_directory(target)
    (target / "backend/injected.py").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="file list"):
        packager.verify_directory(target)


@pytest.mark.parametrize("entry", ["../agent.py", "/absolute.py", "backend\\escape.py", "backend/cache/entry.json", "backend/config/new.key", "backend/.git/config", "backend/.env/config.json", "backend/vector_store/retrieval.py", "backend/VECTOR_STORE/config.py"])
def test_archive_verification_rejects_unsafe_member_names(context, tmp_path, entry):
    archive = tmp_path / "customer.zip"
    packager.export_archive(context, archive, no_git_context=True)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr(entry, "unsafe")
    # ZipInfo normalizes Windows backslashes; either unsafe-name or manifest
    # rejection must still stop distribution on that platform.
    with pytest.raises(ValueError, match="Forbidden|file list"):
        packager.verify_archive(archive)


def test_archive_symlink_member_is_rejected(context, tmp_path):
    archive = tmp_path / "customer.zip"
    packager.export_archive(context, archive, no_git_context=True)
    with zipfile.ZipFile(archive, "a") as output:
        info = zipfile.ZipInfo("backend/link.py")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(info, "../../keys.json")
    with pytest.raises(ValueError, match="Symlink"):
        packager.verify_archive(archive)


def test_customer_source_symlink_is_rejected(context, tmp_path):
    target = context / "backend/linked.py"
    try:
        target.symlink_to(context / "agent.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable for this host account")
    with pytest.raises(ValueError, match="Symlink"):
        packager.export_directory(context, tmp_path / "customer", no_git_context=True)


def test_existing_dist_requires_explicit_opt_in(source, tmp_path):
    (source / "dist").mkdir()
    (source / "dist/index.html").write_text("<html></html>", encoding="utf-8")
    (source / "dist/.env").write_text("PRIVATE", encoding="utf-8")
    assert "dist/index.html" not in packager.select_files(source)
    names = packager.select_files(source, include_dist=True)
    assert "dist/index.html" in names
    assert "dist/.env" not in names
    context = tmp_path / "with-dist"
    packager.export_directory(source, context, include_dist=True)
    assert "dist/index.html" in packager.select_files(context, no_git_context=True, include_dist=True)
    with pytest.raises(ValueError, match="Forbidden"):
        packager.select_files(context, no_git_context=True)
    (context / "dist/unlisted.js").write_text("private bundle", encoding="utf-8")
    with pytest.raises(ValueError, match="file list"):
        packager.select_files(context, no_git_context=True, include_dist=True)


def test_no_git_raw_checkout_requires_existing_manifest(source, tmp_path):
    with pytest.raises(ValueError, match="manifest is missing"):
        packager.export_directory(source, tmp_path / "customer", no_git_context=True)
    assert not (tmp_path / "customer").exists()


def test_build_context_and_subsequent_exports_exclude_untracked_source(source, tmp_path):
    private_names = {"backend/private.py", "frontend/src/private_token.ts"}
    for name in private_names:
        (source / name).write_text("private material", encoding="utf-8")
    context = tmp_path / "context"
    manifest = packager.build_context(source, context)
    assert private_names.isdisjoint(manifest["files"])
    assert packager.BUILD_HELPERS.isdisjoint(manifest["files"])
    assert all((context / name).is_file() for name in packager.BUILD_HELPERS)
    assert all(not (context / name).exists() for name in private_names)
    assert packager.select_files(context, no_git_context=True) == sorted(manifest["files"])
    customer = tmp_path / "customer"
    assert packager.export_directory(context, customer, no_git_context=True) == manifest
    assert all(not (customer / name).exists() for name in private_names | packager.BUILD_HELPERS)
    for root, filename in [(source, "tracked.zip"), (context, "context.zip"), (customer, "customer.zip")]:
        archive = tmp_path / filename
        packager.export_archive(root, archive, no_git_context=root != source)
        with zipfile.ZipFile(archive) as output:
            assert private_names.isdisjoint(output.namelist())
            assert packager.BUILD_HELPERS.isdisjoint(output.namelist())


@pytest.mark.parametrize("helper", sorted(packager.BUILD_HELPERS))
def test_build_context_requires_tracked_helpers(source, tmp_path, helper):
    # Only this disposable fixture's Git index is changed.
    subprocess.run(["git", "-C", str(source), "rm", "--cached", "--quiet", "--", helper], check=True)
    with pytest.raises(ValueError, match="helpers must be tracked"):
        packager.build_context(source, tmp_path / "context")
    assert not (tmp_path / "context").exists()


@pytest.mark.parametrize("helper", sorted(packager.BUILD_HELPERS))
def test_build_context_rejects_helper_symlinks(source, tmp_path, helper):
    path = source / helper
    path.unlink()
    try:
        path.symlink_to(source / "agent.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable for this host account")
    with pytest.raises(ValueError, match="Symlink"):
        packager.build_context(source, tmp_path / "context")


@pytest.mark.parametrize("name", ["backend/private.py", "frontend/src/private_token.ts"])
def test_no_git_rejects_unlisted_allowlisted_source(context, tmp_path, name):
    (context / name).write_text("private source", encoding="utf-8")
    with pytest.raises(ValueError, match="file list"):
        packager.export_directory(context, tmp_path / "customer", no_git_context=True)
    assert not (tmp_path / "customer").exists()


def test_no_git_rejects_changed_and_missing_manifest_members(context, tmp_path):
    member = context / "backend/app_factory.py"
    member.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        packager.export_archive(context, tmp_path / "customer.zip", no_git_context=True)
    assert not (tmp_path / "customer.zip").exists()
    member.unlink()
    with pytest.raises(ValueError, match="file list"):
        packager.select_files(context, no_git_context=True)


@pytest.mark.parametrize("contents", [None, [], "manifest", {"format": 1, "law_source": "remote", "files": []}, {"format": 1, "law_source": "remote", "files": None}])
def test_no_git_rejects_non_object_manifest_and_file_map(context, contents):
    (context / packager.MANIFEST).write_text(json.dumps(contents), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid customer manifest"):
        packager.select_files(context, no_git_context=True)


@pytest.mark.parametrize("name", ["../agent.py", "/outside.py", "backend\\escape.py", "RAG/data/private.json", "backend/vector_store/internal.py", "scripts/package-customer.py"])
def test_no_git_rejects_unsafe_manifest_members(context, name):
    path = context / packager.MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"][name] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Forbidden customer manifest member"):
        packager.select_files(context, no_git_context=True)


def test_no_git_rejects_invalid_checksum_and_duplicate_manifest_keys(context):
    path = context / packager.MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"]["agent.py"] = []
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid customer manifest checksum"):
        packager.select_files(context, no_git_context=True)
    path.write_text('{"files": {}, "files": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate customer manifest key"):
        packager.select_files(context, no_git_context=True)


def test_build_context_cli_prepares_context_and_rejects_unsafe_combinations(source, tmp_path, monkeypatch):
    monkeypatch.setattr(packager, "ROOT", source)
    target = tmp_path / "cli-context"
    assert packager.main(["--build-context", str(target)]) == 0
    assert (target / packager.MANIFEST).is_file()
    for option in ["--no-git-context", "--include-dist"]:
        with pytest.raises(SystemExit) as error:
            packager.main(["--build-context", str(tmp_path / "rejected"), option])
        assert error.value.code == 2
    assert not (tmp_path / "rejected").exists()


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
