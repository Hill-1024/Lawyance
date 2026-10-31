"""Interrupted preparation keeps recovery metadata and blocks an unsafe rerun."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy/prepare_law_remote.py"
SPEC = importlib.util.spec_from_file_location("prepare_interruption_parent", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


CHILD = r'''
import importlib.util, json, os, sys
from pathlib import Path

script, root, moment = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location("prepare_interruption_child", script)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
env_path = root / ".env"
real_replace = os.replace

def interrupted_replace(source, destination, *args, **kwargs):
    if Path(destination).absolute() == env_path.absolute():
        if moment == "before-switch":
            os._exit(71)
        result = real_replace(source, destination, *args, **kwargs)
        os._exit(72)
    return real_replace(source, destination, *args, **kwargs)

prepare.os.replace = interrupted_replace
state = json.loads((root / "fixture-state.json").read_text())
prepare.prepare_configuration(env_path, root / "candidate.env", root / "central.json", state)
raise SystemExit("interruption hook did not run")
'''


@pytest.mark.parametrize("moment,exit_code", [("before-switch", 71), ("after-switch", 72)])
def test_process_interruption_keeps_preparing_record_and_blocks_rerun(tmp_path, moment, exit_code):
    root = tmp_path / "isolated-configuration"
    root.mkdir()
    assert root.resolve().is_relative_to(tmp_path.resolve())
    env_path, candidate = root / ".env", root / "candidate.env"
    original, proposed = b"UNCHANGED_SETTING=fixture\nLAWVER_LAW_SOURCE=local\n", b"UNCHANGED_SETTING=fixture\nLAWVER_LAW_SOURCE=remote\n"
    env_path.write_bytes(original)
    candidate.write_bytes(proposed)
    backup = root / "private-backup"
    backup.mkdir()
    shutil.copy2(env_path, backup / "cn.env")
    metadata = env_path.stat()
    state = {
        "head": "a" * 40, "unit": "fixture.service", "project_root": str(root),
        "old_main_pid": 123, "config_backup": str(backup / "cn.env"),
        "config_uid": metadata.st_uid, "config_gid": metadata.st_gid,
        "config_mode": stat.S_IMODE(metadata.st_mode),
        "old_env_sha256": hashlib.sha256(original).hexdigest(),
        "new_env_sha256": hashlib.sha256(proposed).hexdigest(),
    }
    (root / "fixture-state.json").write_text(json.dumps(state), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(SCRIPT), str(root), moment],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == exit_code, completed.stderr
    central = root / "central.json"
    record_bytes = central.read_bytes()
    record = json.loads(record_bytes)
    assert record["phase"] == "preparing"
    assert record["old_env_sha256"] == state["old_env_sha256"]
    assert record["new_env_sha256"] == state["new_env_sha256"]
    assert (backup / "cn.env").read_bytes() == original
    assert json.loads((backup / "state.json").read_text())["phase"] == "preparing"
    expected = original if moment == "before-switch" else proposed
    assert env_path.read_bytes() == expected
    candidate.write_bytes(proposed)
    with pytest.raises((FileExistsError, RuntimeError)):
        prepare.prepare_configuration(env_path, candidate, central, state)
    assert env_path.read_bytes() == expected
    assert central.read_bytes() == record_bytes
    assert (backup / "cn.env").read_bytes() == original
