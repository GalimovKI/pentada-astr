#!/usr/bin/env python3
"""Root-owned SSH forced command. Only stage/activate/current are supported."""
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


def command(value):
    if value == 'current':
        return 'current', None
    match = re.fullmatch(r'(stage|activate) ([0-9a-f]{7,40})', value)
    if not match:
        raise ValueError('Only current, stage SHA and activate SHA are allowed')
    return match.groups()


def extract(archive, destination):
    # Reject traversal, symlinks, hardlinks, devices, and oversized archives.
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


def compose(release, *args):
    env = {**os.environ, 'APP_IMAGE_TAG': release.name}
    subprocess.run(['docker', 'compose', '-p', 'pentada-edge', '-f',
                    str(release / 'compose.edge.yaml'), *args],
                   env=env, stdin=subprocess.DEVNULL, check=True)


def activate(release):
    if not (release / 'compose.edge.yaml').is_file():
        raise ValueError('Release is not staged')
    previous = (ROOT / 'current').resolve(strict=True)
    try:
        compose(release, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120')
    except subprocess.CalledProcessError:
        compose(previous, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120')
        raise
    link = ROOT / 'current.next'
    link.unlink(missing_ok=True)
    link.symlink_to(release)
    link.replace(ROOT / 'current')


def main():
    action, sha = command(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    os.umask(0o022)
    with (ROOT / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == 'current':
            print((ROOT / 'current').resolve(strict=True).name)
            return
        release = ROOT / 'releases' / sha
        if action == 'stage':
            with tempfile.TemporaryDirectory(dir=ROOT / 'releases', prefix='.stage-') as temp:
                with tarfile.open(fileobj=sys.stdin.buffer, mode='r|gz') as archive:
                    extract(archive, Path(temp))
                (Path(temp) / 'RELEASE_SHA').write_text(sha + '\n')
                if not release.exists():
                    # Preserve an existing immutable release on retries.
                    Path(temp).rename(release)
            compose(release, 'build', 'web')
        else:
            activate(release)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Edge deployment failed: {error}', file=sys.stderr)
        sys.exit(1)
