"""Configuration preparation must preserve unrelated secrets and tolerate empty unit properties."""
import ast
import importlib.util
from pathlib import Path

import pytest
from dotenv import dotenv_values


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy/prepare_law_remote.py"
SPEC = importlib.util.spec_from_file_location("prepare_law_remote", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def test_missing_environment_files_is_an_empty_optional_property():
    properties = prepare.parse_properties(
        "User=service-user\nWorkingDirectory=/srv/lawver\nDropInPaths=\n"
    )
    assert properties.get("EnvironmentFiles", "") == ""
    assert properties["User"] == "service-user"


@pytest.mark.parametrize("source_text", [
    '# comment\nLAWVER_DATABASE_URL="postgresql://dummy:dummy@127.0.0.1/lawver"\nSECRET_KEY=unchanged\n',
    'MULTILINE="first\nsecond"\nLAWVER_LAW_SOURCE=local\nLAWVER_LAW_SOURCE=local\n',
    "EMPTY=\nBARE\nQUOTED='value with spaces # kept'\nREF=${OTHER:-fallback}\n",
    'HTTP_PROXY="http://proxy.invalid:3128"\nNO_PROXY="model.internal"\nno_proxy="search.internal"\n',
])
def test_candidate_preserves_non_law_configuration_and_original_file(tmp_path, source_text):
    original = tmp_path / "original.env"
    candidate = tmp_path / "candidate.env"
    original.write_text(source_text, encoding="utf-8")
    original_bytes = original.read_bytes()
    desired = {
        "LAWVER_LAW_SOURCE": "remote",
        "LAWVER_LAW_SERVICE_URL": "http://127.0.0.1:8084",
        "LAWVER_LAW_SERVICE_KEY": "lvk_dummy_verification_only",
        "LAWVER_LAW_SERVICE_TIMEOUT": "10",
    }
    prepare.build_candidate(original, candidate, desired)
    before = dotenv_values(original, interpolate=False)
    after = dotenv_values(candidate, interpolate=False)
    assert original.read_bytes() == original_bytes
    assert {key: value for key, value in after.items() if key not in desired} == {
        key: value for key, value in before.items() if key not in desired
    }
    assert all(after[name] == value for name, value in desired.items())


def test_commit_and_staging_paths_are_runtime_arguments():
    arguments = prepare.parse_arguments([
        "--expected-head", "a" * 40,
        "--frontend-staging", "TEMP/frontend-release",
    ])
    assert arguments.project_root == SCRIPT.parents[2]
    assert arguments.frontend_staging == Path("TEMP/frontend-release")
    assert arguments.expected_head == "a" * 40
    assert arguments.patch_manifest is None
    ast.parse(prepare.PROBE)


def test_database_configuration_does_not_require_a_frontend_build():
    arguments = prepare.parse_arguments(["--expected-head", "a" * 40])
    assert arguments.frontend_staging is None


@pytest.mark.parametrize("extra", [
    ["--patch-manifest", "manifest.json"],
    ["--patch-manifest-sha", "a" * 64],
    ["--timeout", "nan"],
    ["--timeout", "0"],
])
def test_invalid_operator_arguments_fail_before_any_deployment(extra):
    with pytest.raises(SystemExit) as error:
        prepare.parse_arguments([
            "--expected-head", "a" * 40,
            "--frontend-staging", "TEMP/frontend-release",
            *extra,
        ])
    assert error.value.code == 2
