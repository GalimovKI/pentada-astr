#!/usr/bin/env python3
"""Run on the academic host after CI. Deployment settings stay outside Git."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def main():
    config = json.loads((Path.home() / '.config/pentada-ci.json').read_text())
    root = Path(config['origin_root']).expanduser().resolve()
    env_file = root / 'shared/.env.production'
    docker = str(Path(config['docker']).expanduser())
    ssh = ['ssh', '-F', str(Path(config['ssh_config']).expanduser()), 'pentada-deploy']
    sha = output('git', 'rev-parse', 'HEAD')
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Invalid commit')
    if os.environ.get('GITHUB_SHA') and sha != os.environ['GITHUB_SHA']:
        raise ValueError('Checkout is not the requested commit')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        latest = output('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0]
        if sha != latest:
            print('A newer main commit exists; skipping obsolete deployment.')
            return
    if output('git', 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked source files must be clean')

    os.environ['PATH'] = str(Path(docker).parent) + ':' + os.environ['PATH']
    # Explicit source/settings locations avoid checkout cleanup touching runtime data.
    with (root / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = (root / 'current').resolve(strict=True)
        previous_edge = output(*ssh, 'current')
        if not re.fullmatch('[0-9a-f]{7,40}', previous_edge):
            raise ValueError('Invalid previous edge release')
        release = root / 'releases' / sha
        with tempfile.TemporaryDirectory(dir=root / 'releases', prefix='.stage-') as temp:
            archive = Path(temp) / 'source.tar.gz'
            run('git', 'archive', '--format=tar.gz', '-o', archive, sha)
            if not release.exists():
                source = Path(temp) / 'source'
                source.mkdir(mode=0o755)
                run('tar', '-xzf', archive, '-C', source)
                # The service has umask 077; mounted configs must be readable by UID 10001.
                for directory, _, files in os.walk(source):
                    Path(directory).chmod(0o755)
                    for name in files:
                        path = Path(directory) / name
                        if not path.is_symlink():
                            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
                (source / 'RELEASE_SHA').write_text(sha + '\n')
                source.rename(release)

            def compose(target, *args, **kwargs):
                env = {**os.environ, 'APP_IMAGE_TAG': target.name}
                return run(docker, '--context', 'rootless', 'compose', '--env-file', env_file,
                           '-p', 'pentada-mailsearch', '-f', target / 'compose.production.yaml',
                           '-f', target / 'compose.origin.yaml', *args, env=env,
                           stdin=subprocess.DEVNULL, **kwargs)

            # Both builds finish before touching the running containers.
            compose(release, 'build', 'backend')
            with archive.open('rb') as stream:
                run(*ssh, f'stage {sha}', stdin=stream)

        # Schema changes require a deliberate migration plan, not a blind auto-rollback.
        def migrations(path):
            return {p.relative_to(path): p.read_bytes() for p in
                    (path / 'backend/migrations').rglob('*') if p.is_file()}
        if migrations(previous) != migrations(release):
            raise RuntimeError('Migrations changed: deploy manually using DEPLOYMENT.md first')

        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = root / 'backups' / f'{stamp}-{sha[:12]}'
        backup.mkdir(mode=0o700, parents=True)
        shutil.copyfile(env_file, backup / '.env.production')
        (backup / '.env.production').chmod(0o600)
        (backup / 'previous.json').write_text(json.dumps({
            'origin': str(previous), 'edge': previous_edge, 'target': sha}, indent=2))
        with (backup / 'database.dump').open('wb') as stream:
            compose(previous, 'exec', '-T', 'db', 'sh', '-c',
                    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc', stdout=stream)
        (backup / 'database.dump').chmod(0o600)
        try:
            compose(release, 'run', '--rm', '--no-deps', 'prepare')
            compose(release, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '300', 'db', 'backend')
            run(*ssh, f'activate {sha}', stdin=subprocess.DEVNULL)
            run('python3', release / 'scripts/check_production.py', '--url', config['public_url'])
            link = root / 'current.next'
            link.unlink(missing_ok=True)
            link.symlink_to(release)
            link.replace(root / 'current')
        except BaseException:
            # Restore code only; never overwrite the live database automatically.
            try:
                compose(previous, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '300', 'db', 'backend')
            finally:
                run(*ssh, f'activate {previous_edge}', stdin=subprocess.DEVNULL)
            raise
        print(f'Deployed {sha}; backup: {backup}')


if __name__ == '__main__':
    main()
