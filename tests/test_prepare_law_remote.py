"""Configuration preparation must preserve unrelated secrets and tolerate empty unit properties."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

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


@pytest.fixture
def transaction(tmp_path):
    project = tmp_path / 'project'
    backup = tmp_path / 'private-backup'
    central = tmp_path / 'central'
    for path in (project, backup, central):
        path.mkdir()
    env_path = project / '.env'
    old = b'LAWVER_LAW_SOURCE=local\r\nUNRELATED=dummy-fixture\r\n'
    new = b'LAWVER_LAW_SOURCE=remote\nUNRELATED=dummy-fixture\n'
    env_path.write_bytes(old)
    env_path.chmod(0o640)
    candidate = project / 'candidate.env'
    candidate.write_bytes(new)
    candidate.chmod(0o600)
    saved = backup / 'cn.env'
    saved.write_bytes(old)
    saved.chmod(0o600)
    details = env_path.stat()
    state = {
        'head': 'a' * 40, 'unit': 'fixture.service', 'project_root': str(project),
        'old_main_pid': 123, 'config_backup': str(saved),
        'config_uid': details.st_uid, 'config_gid': details.st_gid,
        'config_mode': stat.S_IMODE(details.st_mode),
        'old_env_sha256': prepare.sha(env_path), 'new_env_sha256': prepare.sha(candidate),
        'frontend_staging': str(project / 'frontend'), 'frontend_index_sha256': 'b' * 64,
    }
    return SimpleNamespace(env_path=env_path, candidate=candidate,
                           state_file=central / 'prepared.json', state=state,
                           old=old, new=new, backup=saved,
                           candidate_mode=stat.S_IMODE(candidate.stat().st_mode))


def run_transaction(case):
    return prepare.prepare_configuration(case.env_path, case.candidate, case.state_file, case.state)


def assert_old_configuration(case):
    assert case.env_path.read_bytes() == case.old
    assert prepare.sha(case.env_path) == case.state['old_env_sha256']
    assert stat.S_IMODE(case.env_path.stat().st_mode) == case.state['config_mode']
    if os.name == 'posix':
        assert case.env_path.stat().st_uid == case.state['config_uid']
        assert case.env_path.stat().st_gid == case.state['config_gid']
    assert case.backup.read_bytes() == case.old


def assert_rolled_back(case):
    assert_old_configuration(case)
    assert not case.state_file.exists()
    recovery = json.loads((case.backup.parent / 'state.json').read_text())
    assert recovery['phase'] == 'preparing'
    assert recovery['old_env_sha256'] == case.state['old_env_sha256']
    assert not list(case.state_file.parent.glob('.prepared.json-*'))
    assert not list(case.env_path.parent.glob('.env-restore-*'))


def test_transaction_publishes_prepared_after_durable_recovery_snapshot(transaction):
    case = transaction
    result = run_transaction(case)
    assert result == json.loads(case.state_file.read_text())
    assert result['phase'] == 'prepared'
    assert result['config_path'] == str(case.env_path.absolute())
    assert all(result[name] == value for name, value in case.state.items())
    assert case.env_path.read_bytes() == case.new
    assert stat.S_IMODE(case.env_path.stat().st_mode) == case.candidate_mode
    assert not case.candidate.exists()
    recovery = json.loads((case.backup.parent / 'state.json').read_text())
    assert recovery == {**result, 'phase': 'preparing'}
    assert case.backup.read_bytes() == case.old


def test_existing_central_record_blocks_without_changing_or_deleting_it(transaction):
    case = transaction
    case.state_file.write_bytes(b'other preparation record')
    with pytest.raises(RuntimeError, match='already exists'):
        run_transaction(case)
    assert case.state_file.read_bytes() == b'other preparation record'
    assert_old_configuration(case)
    assert not (case.backup.parent / 'state.json').exists()


def test_partial_backup_record_is_cleaned_before_central_record_or_env_change(transaction, monkeypatch):
    case = transaction

    def partial_write(descriptor, record):
        os.write(descriptor, b'{"partial":')
        raise OSError('injected backup record write failure')

    monkeypatch.setattr(prepare, '_write_record_fd', partial_write)
    with pytest.raises(OSError, match='backup record write failure'):
        run_transaction(case)
    assert_old_configuration(case)
    assert not case.state_file.exists()
    assert not (case.backup.parent / 'state.json').exists()


@pytest.mark.parametrize('failure', ['create', 'partial-write', 'file-fsync', 'directory-fsync', 'candidate-fsync'])
def test_central_record_failures_never_switch_env(transaction, monkeypatch, failure):
    case = transaction
    real_exclusive = prepare._exclusive_record
    real_write = prepare._write_record_fd
    real_file_sync = prepare._fsync_file
    real_directory_sync = prepare._fsync_directory
    real_fsync = prepare.os.fsync
    real_replace = prepare.os.replace
    replacements = []
    fired = False

    def exclusive(path, record, identities):
        if path == case.state_file and failure == 'create':
            raise PermissionError('injected central create failure')
        return real_exclusive(path, record, identities)

    def write(descriptor, record):
        if failure == 'partial-write' and case.state_file.exists():
            os.write(descriptor, b'{"partial":')
            raise OSError('injected partial write')
        return real_write(descriptor, record)

    def fsync(descriptor):
        if failure == 'file-fsync' and case.state_file.exists():
            if prepare._identity(os.fstat(descriptor)) == prepare._identity(case.state_file.stat()):
                raise OSError('injected central fsync failure')
        return real_fsync(descriptor)

    def file_sync(path):
        if failure == 'candidate-fsync' and path == case.candidate:
            raise OSError('injected candidate fsync failure')
        return real_file_sync(path)

    def directory_sync(path):
        nonlocal fired
        if failure == 'directory-fsync' and path == case.state_file.parent and not fired:
            fired = True
            raise OSError('injected central directory fsync failure')
        return real_directory_sync(path)

    def replace(source, target):
        replacements.append((Path(source), Path(target)))
        return real_replace(source, target)

    monkeypatch.setattr(prepare, '_exclusive_record', exclusive)
    monkeypatch.setattr(prepare, '_write_record_fd', write)
    monkeypatch.setattr(prepare.os, 'fsync', fsync)
    monkeypatch.setattr(prepare, '_fsync_file', file_sync)
    monkeypatch.setattr(prepare, '_fsync_directory', directory_sync)
    monkeypatch.setattr(prepare.os, 'replace', replace)
    with pytest.raises((RuntimeError, PermissionError)):
        run_transaction(case)
    assert_rolled_back(case)
    assert case.candidate.read_bytes() == case.new
    assert replacements == []


def test_exclusive_create_race_keeps_the_other_record(transaction, monkeypatch):
    case = transaction
    real_exclusive = prepare._exclusive_record

    def competing_create(path, record, identities):
        if path == case.state_file:
            path.write_bytes(b'concurrent owner')
        return real_exclusive(path, record, identities)

    monkeypatch.setattr(prepare, '_exclusive_record', competing_create)
    with pytest.raises(FileExistsError):
        run_transaction(case)
    assert case.state_file.read_bytes() == b'concurrent owner'
    assert_old_configuration(case)


@pytest.mark.parametrize('failure', ['replace-before', 'replace-after', 'sha', 'file-fsync', 'directory-fsync', 'prepared-write', 'prepared-replace', 'prepared-replace-after', 'prepared-directory-fsync'])
def test_failures_during_or_after_env_switch_restore_original(transaction, monkeypatch, failure):
    case = transaction
    real_replace = prepare.os.replace
    real_sha = prepare.sha
    real_file_sync = prepare._fsync_file
    real_directory_sync = prepare._fsync_directory
    real_write = prepare._write_record_fd
    fired = False

    def replace(source, target):
        source, target = Path(source), Path(target)
        if source == case.candidate and target == case.env_path:
            # The journal must already be complete before any .env replacement.
            assert json.loads(case.state_file.read_text())['phase'] == 'preparing'
            if failure == 'replace-before':
                raise OSError('injected env replacement failure')
            real_replace(source, target)
            if failure == 'replace-after':
                raise OSError('injected failure after env rename')
            return
        if target == case.state_file:
            if failure == 'prepared-replace':
                raise OSError('injected prepared publication failure')
            real_replace(source, target)
            if failure == 'prepared-replace-after':
                raise OSError('injected failure after prepared publication')
            return
        return real_replace(source, target)

    def checksum(path):
        nonlocal fired
        result = real_sha(path)
        if failure == 'sha' and path == case.env_path and result == case.state['new_env_sha256'] and not fired:
            fired = True
            return '0' * 64
        return result

    def file_sync(path):
        if failure == 'file-fsync' and path == case.env_path:
            raise OSError('injected switched configuration fsync failure')
        return real_file_sync(path)

    def directory_sync(path):
        nonlocal fired
        if not fired and failure == 'directory-fsync' and path == case.env_path.parent:
            fired = True
            raise OSError('injected configuration directory fsync failure')
        if not fired and failure == 'prepared-directory-fsync' and path == case.state_file.parent:
            if case.state_file.exists() and json.loads(case.state_file.read_text())['phase'] == 'prepared':
                fired = True
                raise OSError('injected prepared directory fsync failure')
        return real_directory_sync(path)

    def write(descriptor, record):
        if failure == 'prepared-write' and record['phase'] == 'prepared':
            os.write(descriptor, b'{"partial":')
            raise OSError('injected prepared write failure')
        return real_write(descriptor, record)

    monkeypatch.setattr(prepare.os, 'replace', replace)
    monkeypatch.setattr(prepare, 'sha', checksum)
    monkeypatch.setattr(prepare, '_fsync_file', file_sync)
    monkeypatch.setattr(prepare, '_fsync_directory', directory_sync)
    monkeypatch.setattr(prepare, '_write_record_fd', write)
    with pytest.raises(RuntimeError, match='original configuration SHA256/mode verified'):
        run_transaction(case)
    assert_rolled_back(case)


def test_failed_restore_retains_preparing_record_and_blocks_rerun(transaction, monkeypatch):
    case = transaction
    real_replace = prepare.os.replace
    real_write = prepare._write_record_fd

    def write(descriptor, record):
        if record['phase'] == 'prepared':
            raise OSError('injected final record failure')
        return real_write(descriptor, record)

    def replace(source, target):
        if Path(source).name.startswith('.env-restore-'):
            raise OSError('injected restore failure')
        return real_replace(source, target)

    monkeypatch.setattr(prepare, '_write_record_fd', write)
    monkeypatch.setattr(prepare.os, 'replace', replace)
    with pytest.raises(RuntimeError, match='rollback failed.*Do not rerun'):
        run_transaction(case)
    assert case.env_path.read_bytes() == case.new
    assert json.loads(case.state_file.read_text())['phase'] == 'preparing'
    assert (case.backup.parent / 'state.json').is_file()
    assert case.backup.read_bytes() == case.old
    with pytest.raises(RuntimeError, match='already exists'):
        run_transaction(case)
    assert case.env_path.read_bytes() == case.new


def test_restore_sha_verification_failure_keeps_recovery_records(transaction, monkeypatch):
    case = transaction
    real_replace = prepare.os.replace

    def fail_publication(*args):
        raise OSError('injected final publication failure')

    def replace(source, target):
        real_replace(source, target)
        if Path(source).name.startswith('.env-restore-'):
            case.env_path.write_bytes(b'injected restored-file corruption')

    monkeypatch.setattr(prepare, '_publish_record', fail_publication)
    monkeypatch.setattr(prepare.os, 'replace', replace)
    with pytest.raises(RuntimeError, match='rollback failed.*Do not rerun'):
        run_transaction(case)
    assert prepare.sha(case.env_path) != case.state['old_env_sha256']
    assert json.loads(case.state_file.read_text())['phase'] == 'preparing'
    assert (case.backup.parent / 'state.json').is_file()
    assert case.backup.read_bytes() == case.old
    with pytest.raises(RuntimeError, match='already exists'):
        run_transaction(case)


def test_record_ownership_change_is_neither_overwritten_nor_removed(transaction, monkeypatch):
    case = transaction
    real_publish = prepare._publish_record

    def foreign_publish(path, record, identities):
        foreign = path.parent / 'foreign.json'
        foreign.write_bytes(b'foreign deployment record')
        os.replace(foreign, path)
        return real_publish(path, record, identities)

    monkeypatch.setattr(prepare, '_publish_record', foreign_publish)
    with pytest.raises(RuntimeError, match='record cleanup failed.*Do not rerun'):
        run_transaction(case)
    assert_old_configuration(case)
    assert case.state_file.read_bytes() == b'foreign deployment record'
