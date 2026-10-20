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
    (backup / 'state.json').write_text(json.dumps(state, indent=2) + '\n')
    print('CN_ENV_BACKUP_OK: ' + str(backup), flush=True)
    os.replace(candidate, env_path)
    require(sha(env_path) == state['new_env_sha256'], 'Updated CN configuration SHA256 mismatch.')
    with STATE.open('x') as output:
        output.write(json.dumps(state, indent=2) + '\n')
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
