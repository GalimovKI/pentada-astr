#!/usr/bin/env python3
"""Root-owned SSH forced command for independent main/dev frontend releases."""
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path('/opt/pentada')
PORTS = {'main': (18080, 18081, 18082), 'dev': (18090, 18091, 18092)}


def command(value):
    match = re.fullmatch(r'(current|check) (main|dev)', value)
    if match:
        return *match.groups(), None
    match = re.fullmatch(r'(stage|activate|deactivate) (main|dev) ([0-9a-f]{40})', value)
    if not match:
        raise ValueError('Expected current/check ENV or stage/activate/deactivate ENV SHA40')
    return match.groups()


def extract(archive, destination):
    size = 0
    for member in archive:
        path = PurePosixPath(member.name)
        size += member.size
        if (path.is_absolute() or '..' in path.parts or
                not (member.isfile() or member.isdir()) or size > 256 * 1024**2):
            raise ValueError('Invalid source archive')
        target = destination.joinpath(*path.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def compose(environment, release, *args):
    http, tunnel, health = PORTS[environment]
    env = {**os.environ, 'APP_IMAGE_TAG': f'{environment}-{release.name}',
           'APP_BASE_PATH': f'/{environment}/', 'TUNNEL_PORT': str(tunnel),
           'WEB_HEALTH_PORT': str(health), 'SITE_ADDRESS': f'http://:{http}',
           'WEB_BIND': '127.0.0.1'}
    subprocess.run(['docker', 'compose', '-p', f'pentada-edge-{environment}', '-f',
                    str(release / 'compose.edge.yaml'), *args],
                   env=env, stdin=subprocess.DEVNULL, check=True)


def check(environment, release):
    subprocess.run(['python3', str(release / 'scripts/check_production.py'), '--url',
                    f'http://127.0.0.1:{PORTS[environment][0]}/{environment}'],
                   stdin=subprocess.DEVNULL, check=True)


def activate(environment, release):
    if not (release / 'compose.edge.yaml').is_file():
        raise ValueError('Release is not staged')
    root = ROOT / 'environments' / environment
    previous = (root / 'current').resolve(strict=True) if (root / 'current').exists() else None
    try:
        compose(environment, release, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120')
        check(environment, release)
    except subprocess.CalledProcessError:
        if previous:
            compose(environment, previous, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120')
        else:
            compose(environment, release, 'stop', 'web')
        raise
    link = root / 'current.next'
    link.unlink(missing_ok=True)
    link.symlink_to(release)
    link.replace(root / 'current')


def main():
    action, environment, sha = command(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    os.umask(0o022)
    root = ROOT / 'environments' / environment
    (root / 'releases').mkdir(parents=True, exist_ok=True)
    # Shared edge host: never build or activate two versions concurrently.
    with (ROOT / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action in ('current', 'check'):
            current = (root / 'current').resolve(strict=True) if (root / 'current').exists() else None
            if action == 'current':
                print(current.name if current else 'none')
            elif current:
                check(environment, current)
            else:
                raise ValueError('No active release')
            return
        release = root / 'releases' / sha
        if action == 'stage':
            with tempfile.TemporaryDirectory(dir=root / 'releases', prefix='.stage-') as temp:
                with tarfile.open(fileobj=sys.stdin.buffer, mode='r|gz') as archive:
                    extract(archive, Path(temp))
                (Path(temp) / 'RELEASE_SHA').write_text(sha + '\n')
                if not release.exists():
                    Path(temp).rename(release)
            compose(environment, release, 'build', 'web')
        elif action == 'activate':
            activate(environment, release)
        else:
            if (root / 'current').exists() and (root / 'current').resolve() != release:
                raise ValueError('Refusing to stop a different release')
            compose(environment, release, 'stop', 'web')
            (root / 'current').unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Edge deployment failed: {error}', file=sys.stderr)
        sys.exit(1)
