#!/usr/bin/env python3
"""Prepare CN remote-law configuration without restarting services or publishing assets."""
from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from dotenv import dotenv_values, set_key

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
LAW_NAMES = ('LAWVER_LAW_SOURCE', 'LAWVER_LAW_SERVICE_URL',
             'LAWVER_LAW_SERVICE_KEY', 'LAWVER_LAW_SERVICE_TIMEOUT')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(root):
    return subprocess.check_output(
        ['git', '-c', f'safe.directory={root}', '-C', str(root), 'rev-parse', 'HEAD'],
        text=True,
    ).strip()


def parse_properties(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def build_candidate(original, candidate, desired):
    """Preserve all unrelated parsed assignments and their literal values."""
    before = dict(dotenv_values(original, interpolate=False))
    shutil.copy2(original, candidate)
    for name, value in desired.items():
        result = set_key(str(candidate), name, value, quote_mode='always')
        require(result[0] is True, 'Candidate configuration update failed.')
    after = dict(dotenv_values(candidate, interpolate=False))
    require(all(after.get(k) == v for k, v in desired.items()),
            'Candidate configuration does not contain the requested values.')
    require({k: v for k, v in before.items() if k not in desired}
            == {k: v for k, v in after.items() if k not in desired},
            'An unrelated configuration value changed; stopping.')


def _identity(details):
    return details.st_dev, details.st_ino


def _owns_record(path, identities):
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(details.st_mode) and _identity(details) in identities


def _fsync_directory(path):
    # Windows cannot open directories for fsync. Linux deployment must exercise it.
    if os.name != 'posix':
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path):
    # Windows' CRT requires a writable descriptor for os.fsync/_commit.
    with path.open('r+b' if os.name == 'nt' else 'rb') as source:
        os.fsync(source.fileno())


def _write_record_fd(descriptor, record):
    data = memoryview((json.dumps(record, indent=2) + '\n').encode('utf-8'))
    while data:
        written = os.write(descriptor, data)
        require(written > 0, 'Preparation record write made no progress.')
        data = data[written:]
    os.fsync(descriptor)


def _exclusive_record(path, record, identities):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        identities.add(_identity(os.fstat(descriptor)))
        _write_record_fd(descriptor, record)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _remove_owned_record(path, identities):
    require(_owns_record(path, identities),
            'Preparation record ownership changed; refusing to remove it: ' + str(path))
    path.unlink()
    _fsync_directory(path.parent)


def _publish_record(path, record, identities):
    descriptor, temporary_name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        identities.add(_identity(os.fstat(descriptor)))
        try:
            _write_record_fd(descriptor, record)
        finally:
            os.close(descriptor)
        require(_owns_record(path, identities),
                'Preparation record ownership changed; refusing to overwrite it: ' + str(path))
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if _owns_record(temporary, identities):
            temporary.unlink()


def _original_matches(env_path, state):
    if env_path.is_symlink() or not env_path.is_file():
        return False
    details = env_path.stat()
    return (sha(env_path) == state['old_env_sha256']
            and stat.S_IMODE(details.st_mode) == state['config_mode']
            and (os.name != 'posix' or (details.st_uid, details.st_gid)
                 == (state['config_uid'], state['config_gid'])))


def _restore_configuration(env_path, state):
    if _original_matches(env_path, state):
        return
    backup = Path(state['config_backup'])
    require(not backup.is_symlink() and backup.is_file() and sha(backup) == state['old_env_sha256'],
            'Original configuration backup SHA256 mismatch; manual recovery is required.')
    descriptor, temporary_name = tempfile.mkstemp(prefix='.env-restore-', dir=env_path.parent)
    temporary = Path(temporary_name)
    identity = _identity(os.fstat(descriptor))
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(backup.read_bytes())
            output.flush()
            if os.name == 'posix':
                os.chown(temporary, state['config_uid'], state['config_gid'])
            os.chmod(temporary, state['config_mode'])
            os.fsync(output.fileno())
        require(_original_matches(temporary, state), 'Restored configuration candidate verification failed.')
        os.replace(temporary, env_path)
        _fsync_directory(env_path.parent)
        require(_original_matches(env_path, state), 'Restored CN configuration SHA256/mode verification failed.')
    finally:
        if _owns_record(temporary, {identity}):
            temporary.unlink()


def prepare_configuration(env_path, candidate, state_file, state):
    """Commit a probed candidate, or restore the old file after ordinary failures.

    The exclusive central record is a cooperative deployment lock. An interrupted
    run deliberately leaves it in place; inspect old/new SHA256 before recovery.
    The backup record is an immutable recovery snapshot, never a success marker.
    """
    env_path, candidate, state_file = map(Path, (env_path, candidate, state_file))
    backup = Path(state['config_backup'])
    backup_record = backup.parent / 'state.json'
    require(not state_file.exists() and not state_file.is_symlink(),
            'Preparation record already exists; report this without rerunning deployment.')
    require(len({path.resolve() for path in (env_path, candidate, state_file, backup, backup_record)}) == 5,
            'Preparation and recovery paths must be distinct.')
    require(_original_matches(env_path, state), 'Original CN configuration changed before preparation.')
    require(not candidate.is_symlink() and candidate.is_file() and sha(candidate) == state['new_env_sha256'],
            'Candidate CN configuration SHA256 mismatch.')
    require(not backup.is_symlink() and backup.is_file() and sha(backup) == state['old_env_sha256'],
            'Original CN configuration backup SHA256 mismatch.')
    preparing = {**state, 'config_path': str(env_path.absolute()), 'phase': 'preparing'}
    prepared = {**preparing, 'phase': 'prepared'}
    _fsync_file(backup)
    _fsync_directory(backup.parent)
    backup_identities = set()
    try:
        _exclusive_record(backup_record, preparing, backup_identities)
    except Exception:
        if _owns_record(backup_record, backup_identities):
            _remove_owned_record(backup_record, backup_identities)
        raise

    identities = set()
    transition_attempted = False
    try:
        # No production change is allowed before the complete journal is durable.
        _exclusive_record(state_file, preparing, identities)
        _fsync_file(candidate)
        require(_original_matches(env_path, state), 'CN configuration changed during preparation.')
        require(sha(candidate) == state['new_env_sha256'], 'Candidate CN configuration changed during preparation.')
        transition_attempted = True
        os.replace(candidate, env_path)
        _fsync_file(env_path)
        _fsync_directory(env_path.parent)
        require(sha(env_path) == state['new_env_sha256'], 'Updated CN configuration SHA256 mismatch.')
        _publish_record(state_file, prepared, identities)
        return prepared
    except Exception as failure:
        # A failed exclusive create owns nothing; another run's record is untouched.
        if not identities:
            raise
        try:
            if transition_attempted:
                _restore_configuration(env_path, preparing)
            require(_original_matches(env_path, preparing), 'Original CN configuration could not be verified.')
        except Exception as recovery_failure:
            raise RuntimeError(
                'CN configuration rollback failed or could not be verified. Do not rerun preparation; '
                f'recovery records/backups retained: {state_file}, {backup_record}, {backup}'
            ) from recovery_failure
        try:
            _remove_owned_record(state_file, identities)
        except Exception as record_failure:
            raise RuntimeError(
                'Original CN configuration SHA256/mode verified, but preparation record cleanup failed. '
                f'Do not rerun until the record is inspected: {state_file}; recovery backup: {backup}'
            ) from record_failure
        raise RuntimeError('CN preparation failed; original configuration SHA256/mode verified and owned record removed.') from failure


PROBE = r'''
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(sys.argv[1], override=False)
sys.path.insert(0, str(Path.cwd() / 'backend'))
sys.path.insert(0, str(Path.cwd()))
from mcp import law_service_client, pkulaw_client
from mcp import legal_search_router as router

if law_service_client.source() != 'remote':
    raise SystemExit('CN probe: effective LAWVER_LAW_SOURCE is not remote.')
law_service_client.validate_configuration()

def forbid_local(*args, **kwargs):
    raise RuntimeError('Local retrieval is forbidden during this remote probe.')
pkulaw_client._local_search_engine = forbid_local
router._hybrid_search_article = forbid_local
if pkulaw_client.ensure_law_database_ready().get('mode') != 'remote':
    raise SystemExit('CN probe: startup law mode is not remote.')

title = '中华人民共和国民法典'
cases = [
    ('exact', router.get_article, (title, '第一条'), 'content'),
    ('search', router.search_article, ('违约责任',), 'result'),
    ('links', router.get_linked_content, (f'《{title}》第一条',), 'text'),
]
for label, handler, args, field in cases:
    result = json.loads(handler(*args))
    value = result.get(field)
    if result.get('success') is not True or not isinstance(value, str) or not value.strip():
        raise SystemExit('CN probe failed: ' + label)
    print('PASS CN remote tool: ' + label, flush=True)
'''


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description='Prepare CN remote-law configuration using a private backup and a service-user probe. No restart or frontend publication.')
    parser.add_argument('--project-root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--expected-head', required=True, help='Full tested Git commit SHA; obtain after committing the deployment changes.')
    parser.add_argument('--frontend-staging', type=Path, help='Optional existing frontend build under PROJECT_ROOT/TEMP; only records its path and checksum.')
    parser.add_argument('--unit', default='lawver-cn.service')
    parser.add_argument('--keys-file', type=Path, default=Path('/etc/lawver-law/keys.json'))
    parser.add_argument('--key-name', default='cn-main')
    parser.add_argument('--service-url', default='http://127.0.0.1:8084')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--backup-root', type=Path, help='Defaults to the service account home/lawver-backups.')
    parser.add_argument('--state-file', type=Path, default=Path('/etc/lawver-law/cn-prepared.json'))
    parser.add_argument('--patch-manifest', type=Path, help='Optional integrity manifest for the current one-time rollout patch.')
    parser.add_argument('--patch-manifest-sha', help='Required together with --patch-manifest.')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', args.expected_head):
        parser.error('--expected-head must be a full lowercase 40-character Git commit SHA')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a finite positive number')
    if bool(args.patch_manifest) != bool(args.patch_manifest_sha):
        parser.error('--patch-manifest and --patch-manifest-sha must be supplied together')
    if args.patch_manifest_sha and not re.fullmatch(r'[0-9a-f]{64}', args.patch_manifest_sha):
        parser.error('--patch-manifest-sha must be a lowercase SHA256')
    return args


def main():
    args = parse_arguments()
    ROOT = args.project_root.resolve()
    HEAD = args.expected_head
    FRONTEND = args.frontend_staging
    if FRONTEND is not None and not FRONTEND.is_absolute():
        FRONTEND = ROOT / FRONTEND
    STATE = args.state_file
    require(os.name == 'posix' and os.geteuid() == 0, 'Run with sudo and the CN .uv_env Python.')
    import pwd

    os.umask(0o077)
    require(git_head(ROOT) == HEAD, 'CN HEAD changed; stopping.')
    require(not STATE.exists() and not STATE.is_symlink(),
            'Preparation record already exists; report this without rerunning deployment.')
    if FRONTEND is not None:
        require(not FRONTEND.is_symlink() and FRONTEND.resolve().is_relative_to((ROOT / 'TEMP').resolve())
                and (FRONTEND / 'index.html').is_file(), 'Frontend staging directory is invalid.')
    if args.patch_manifest is not None:
        require(sha(args.patch_manifest) == args.patch_manifest_sha, 'Uploaded patch manifest SHA256 mismatch.')
        manifest = json.loads(args.patch_manifest.read_text())
        for item in manifest['files']:
            path = ROOT / item['path']
            require(not path.is_symlink() and path.is_file() and sha(path) == item['new_sha256'],
                    'Patched source changed: ' + item['path'])

    info = parse_properties(subprocess.check_output([
        'systemctl', 'show', args.unit, '--all', '--no-pager',
        '-p', 'User', '-p', 'WorkingDirectory', '-p', 'MainPID',
        '-p', 'ActiveState', '-p', 'EnvironmentFiles',
    ], text=True))
    require(info.get('User') not in (None, '', 'root') and info.get('WorkingDirectory') == str(ROOT)
            and info.get('ActiveState') == 'active', 'CN service settings/state differ from the expected deployment.')
    require(not info.get('EnvironmentFiles', '').strip(),
            'CN has a systemd EnvironmentFile; inspect its precedence before switching .env.')
    pid = int(info.get('MainPID') or 0)
    require(pid > 0, 'CN has no running main process.')
    entries = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    initial = dict(item.decode(errors='replace').split('=', 1) for item in entries if b'=' in item)

    env_path = ROOT / '.env'
    require(env_path.is_file() and not env_path.is_symlink(), 'CN .env must be a regular file.')
    original = env_path.read_bytes()
    original_stat = env_path.stat()
    account = pwd.getpwnam(info['User'])
    policies = json.loads(args.keys_file.read_text())['keys']
    policy = next(item for item in policies if item['name'] == args.key_name)
    require(policy.get('enabled', True) is True, 'The selected API key is disabled.')
    desired = dict(zip(LAW_NAMES, ('remote', args.service_url, policy['key'], format(args.timeout, 'g'))))
    conflicts = [name for name in LAW_NAMES if name in initial and initial[name] != desired[name]]
    require(not conflicts, 'Inherited systemd law settings conflict: ' + ', '.join(conflicts))

    work = Path(tempfile.mkdtemp(prefix='cn-law-config-', dir=ROOT / 'TEMP'))
    candidate = work / '.env'
    build_candidate(env_path, candidate, desired)
    os.chown(work, account.pw_uid, account.pw_gid)
    os.chown(candidate, original_stat.st_uid, original_stat.st_gid)
    os.chmod(candidate, stat.S_IMODE(original_stat.st_mode) & 0o660)
    trial = {**initial, 'PYTHONDONTWRITEBYTECODE': '1'}
    print('Testing CN tools with the candidate configuration...', flush=True)
    subprocess.run(
        [str(ROOT / '.uv_env/bin/python'), '-B', '-c', PROBE, str(candidate)],
        cwd=ROOT, env=trial, check=True,
        user=account.pw_uid, group=account.pw_gid,
        extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
    )
    require(env_path.read_bytes() == original and git_head(ROOT) == HEAD,
            'CN configuration or HEAD changed during the probe; stopping.')

    backup = (args.backup_root or Path(account.pw_dir) / 'lawver-backups') / (
        'cn-before-remote-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(env_path, backup / 'cn.env')
    os.chmod(backup / 'cn.env', 0o600)
    require((backup / 'cn.env').read_bytes() == original, 'CN configuration backup verification failed.')
    state = {
        'head': HEAD, 'unit': args.unit, 'project_root': str(ROOT), 'old_main_pid': pid,
        'config_backup': str(backup / 'cn.env'),
        'config_uid': original_stat.st_uid, 'config_gid': original_stat.st_gid,
        'config_mode': stat.S_IMODE(original_stat.st_mode),
        'old_env_sha256': hashlib.sha256(original).hexdigest(),
        'new_env_sha256': sha(candidate),
    }
    if FRONTEND is not None:
        state.update(frontend_staging=str(FRONTEND),
                     frontend_index_sha256=sha(FRONTEND / 'index.html'))
    print('CN_ENV_BACKUP_OK: ' + str(backup), flush=True)
    prepare_configuration(env_path, candidate, STATE, state)
    try:
        work.rmdir()
    except OSError:
        pass
    print('CN_REMOTE_CONFIG_READY: configuration saved; frontend not published; services not restarted.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError:
        print('CN_PREPARE_FAILED: a preflight command failed; report the output.', file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print('CN_PREPARE_FAILED: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
