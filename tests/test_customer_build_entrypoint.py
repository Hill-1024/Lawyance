"""Run the customer build entrypoint offline with an inspecting Docker stand-in."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def find_bash():
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parent.parent / "bin/bash.exe" if git else None
        return str(candidate) if candidate and candidate.is_file() else None
    return shutil.which("bash")


def shell_path(path):
    value = path.absolute().as_posix()
    return "/" + value[0].lower() + value[2:] if os.name == "nt" else value


BASH = find_bash()
pytestmark = pytest.mark.skipif(not BASH or not shutil.which("git"), reason="Git and Bash required")


@pytest.fixture
def build_project(tmp_path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    files = {
        "agent.py": "# fixture\n", "package.json": "{}\n",
        "pyproject.toml": "[project]\nname='fixture'\n", "uv.lock": "version = 1\n",
        "backend/app_factory.py": "# fixture app\n",
        "frontend/src/main.ts": "// tracked application\n",
        "tools/__init__.py": "# fixture tools\n",
    }
    for name, content in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for name in ("scripts/package-customer.py", "deploy/docker/Dockerfile", "deploy/docker/build-customer.sh"):
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "--all"], check=True)
    for name in ("backend/private.py", "frontend/src/private_token.ts", "tools/internal.py"):
        (project / name).write_text("INTERNAL_FIXTURE_MUST_NOT_SHIP", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    probe = tmp_path / "inspect_docker.py"
    probe.write_text('''import hashlib, json, os, sys
from pathlib import Path
arguments = sys.argv[1:]
context = Path(arguments[-1])
manifest = json.loads((context / "CUSTOMER-MANIFEST.json").read_text())
members = {p.relative_to(context).as_posix() for p in context.rglob("*") if p.is_file()}
helpers = {"scripts/package-customer.py", "deploy/docker/Dockerfile"}
assert members == set(manifest["files"]) | helpers | {"CUSTOMER-MANIFEST.json"}
assert not any("private" in name or "internal" in name for name in members)
for name, digest in manifest["files"].items():
    assert hashlib.sha256((context / name).read_bytes()).hexdigest() == digest
assert arguments[0] == "build"
assert arguments[arguments.index("--target") + 1] == "customer"
assert Path(arguments[arguments.index("--file") + 1]) == context / "deploy/docker/Dockerfile"
Path(os.environ["DOCKER_PROBE_OUTPUT"]).write_text(json.dumps({"arguments": arguments, "context": str(context), "members": sorted(members)}))
raise SystemExit(int(os.environ.get("DOCKER_PROBE_STATUS", "0")))
''', encoding="utf-8", newline="\n")
    docker = fake_bin / "docker"
    docker.write_text('#!/usr/bin/env bash\nexec "$LAWVER_BUILD_PYTHON" "$DOCKER_PROBE_SCRIPT" "$@"\n', encoding="utf-8", newline="\n")
    docker.chmod(0o755)
    temp_root = tmp_path / "isolated-build-temporary"
    temp_root.mkdir()
    environment = os.environ.copy()
    environment.update({
        "LAWVER_BUILD_PYTHON": shell_path(Path(sys.executable)),
        "LAWVER_APP_UID": "1234", "LAWVER_APP_GID": "1235",
        "DOCKER_PROBE_SCRIPT": shell_path(probe),
        "DOCKER_PROBE_OUTPUT": str(tmp_path / "docker-observed.json"),
        "TMPDIR": shell_path(temp_root), "TEST_DOCKER_BIN": shell_path(fake_bin),
    })
    # The source is a disposable repository, including all rename/remove targets.
    assert project.resolve().is_relative_to(tmp_path.resolve())
    assert temp_root.resolve().is_relative_to(tmp_path.resolve())
    return project, environment, temp_root


def run_build(project, environment, cwd):
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-c",
         'export PATH="$TEST_DOCKER_BIN:$PATH"; exec "$BASH" "$@"',
         "customer-build-test", shell_path(project / "deploy/docker/build-customer.sh"), "--tag", "fixture-release"],
        cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45,
    )


@pytest.mark.parametrize("docker_status", [0, 37])
def test_only_tracked_source_reaches_docker_and_temp_is_cleaned(build_project, tmp_path, docker_status):
    project, environment, temporary = build_project
    environment["DOCKER_PROBE_STATUS"] = str(docker_status)
    result = run_build(project, environment, tmp_path)  # Deliberately outside project cwd.
    assert result.returncode == docker_status, result.stderr
    observation = json.loads(Path(environment["DOCKER_PROBE_OUTPUT"]).read_text())
    assert not Path(observation["context"]).exists()
    assert not list(temporary.iterdir())
    arguments = observation["arguments"]
    assert "lawver-customer:fixture-release" in arguments
    assert "APP_UID=1234" in arguments and "APP_GID=1235" in arguments
    assert (project / "backend/private.py").read_text() == "INTERNAL_FIXTURE_MUST_NOT_SHIP"


def test_corpus_gate_failure_does_not_start_docker(build_project, tmp_path):
    project, environment, temporary = build_project
    corpus = project / "RAG/data/law.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text("synthetic corpus", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "RAG/data/law.json"], check=True)
    result = run_build(project, environment, tmp_path)
    assert result.returncode != 0
    assert "still tracked" in result.stderr
    assert not Path(environment["DOCKER_PROBE_OUTPUT"]).exists()
    assert not list(temporary.iterdir())
    assert corpus.read_text() == "synthetic corpus"
