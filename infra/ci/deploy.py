#!/usr/bin/env python3
"""Deploy a reviewed commit into main or dev on the academic host and VPS."""
import argparse
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


def settings(config, environment):
    if environment not in ('main', 'dev'):
        raise ValueError('Environment must be main or dev')
    main, dev = (config['environments'][key] for key in ('main', 'dev'))
    if (Path(main['origin_root']).expanduser().resolve() == Path(dev['origin_root']).expanduser().resolve()
            or main['origin_project'] == dev['origin_project']):
        raise ValueError('main/dev must have separate roots and Compose projects')
    return config['environments'][environment]


def image_tag(release, environment):
    # Old production releases used SHA without environment prefix.
    return f'{environment}-{release.name}' if (release / 'DEPLOYMENT_ENV').exists() else release.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', default=os.environ.get('DEPLOY_ENVIRONMENT'), choices=['main', 'dev'])
    parser.add_argument('--bootstrap', action='store_true', help='Manual first installation before gateway cutover')
    args = parser.parse_args()
    environment = args.environment
    if os.environ.get('GITHUB_ACTIONS') == 'true' and args.bootstrap:
        raise ValueError('Bootstrap is never allowed in CI')
    config = json.loads((Path.home() / '.config/pentada-ci.json').read_text())
    target = settings(config, environment)
    root = Path(target['origin_root']).expanduser().resolve()
    env_file = root / 'shared/.env.production'
    docker = str(Path(config['docker']).expanduser())
    ssh = ['ssh', '-F', str(Path(config['ssh_config']).expanduser()), 'pentada-deploy']
    sha = output('git', 'rev-parse', 'HEAD')
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Invalid commit')
    if os.environ.get('GITHUB_SHA') and sha != os.environ['GITHUB_SHA']:
        raise ValueError('Checkout is not the requested commit')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        if os.environ.get('GITHUB_REF') != f'refs/heads/{environment}':
            raise ValueError('Branch and target environment do not match')
        latest = output('git', 'ls-remote', 'origin', f'refs/heads/{environment}').split()[0]
        if sha != latest:
            print('A newer branch commit exists; skipping obsolete deployment.')
            return
    if output('git', 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked source files must be clean')
    os.environ['PATH'] = str(Path(docker).parent) + ':' + os.environ['PATH']
    with (root / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = (root / 'current').resolve(strict=True) if (root / 'current').exists() else None
        previous_edge = output(*ssh, f'current {environment}')
        if previous_edge != 'none' and not re.fullmatch('[0-9a-f]{40}', previous_edge):
            raise ValueError('Invalid previous edge release')
        release = root / 'releases' / sha
        with tempfile.TemporaryDirectory(dir=root / 'releases', prefix='.stage-') as temp:
            archive = Path(temp) / 'source.tar.gz'
            run('git', 'archive', '--format=tar.gz', '-o', archive, sha)
            if not release.exists():
                source = Path(temp) / 'source'
                source.mkdir(mode=0o755)
                run('tar', '-xzf', archive, '-C', source)
                for directory, _, files in os.walk(source):
                    Path(directory).chmod(0o755)
                    for name in files:
                        path = Path(directory) / name
                        if not path.is_symlink():
                            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
                (source / 'RELEASE_SHA').write_text(sha + '\n')
                (source / 'DEPLOYMENT_ENV').write_text(environment + '\n')
                source.rename(release)

            def compose(version, *arguments, **kwargs):
                env = {**os.environ, 'APP_IMAGE_TAG': image_tag(version, environment)}
                overlays = ['-f', version / 'compose.origin.yaml']
                dev_overlay = version / 'compose.dev-evaluations.yaml'
                if environment == 'dev' and dev_overlay.is_file():
                    overlays.extend(['-f', dev_overlay])
                    gpu_overlay = version / 'compose.dev-gpu.yaml'
                    gpu = os.environ.get('PENTADA_DEV_E5_GPU')
                    if gpu and gpu_overlay.is_file():
                        if not re.fullmatch(r'(?:[0-9]+|GPU-[a-fA-F0-9-]{36})', gpu):
                            raise ValueError('Expected one E5 GPU index or UUID')
                        overlays.extend(['-f', gpu_overlay])
                return run(docker, '--context', 'rootless', 'compose', '--env-file', env_file,
                           '-p', target['origin_project'], '-f', version / 'compose.production.yaml',
                           *overlays, *arguments, env=env,
                           stdin=subprocess.DEVNULL, **kwargs)

            def migrations(path):
                return {p.relative_to(path): p.read_bytes() for p in
                        (path / 'backend/migrations').rglob('*')
                        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
            if previous and migrations(previous) != migrations(release):
                raise RuntimeError('Migrations changed: deploy this environment manually first')
            # Build both images before touching this environment's running containers.
            compose(release, 'build', 'backend')
            with archive.open('rb') as stream:
                run(*ssh, f'stage {environment} {sha}', stdin=stream)

        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        backup = root / 'backups' / f'{stamp}-{sha[:12]}'
        backup.mkdir(mode=0o700, parents=True)
        shutil.copyfile(env_file, backup / '.env.production')
        (backup / '.env.production').chmod(0o600)
        (backup / 'previous.json').write_text(json.dumps({
            'environment': environment, 'origin': str(previous) if previous else None,
            'edge': previous_edge, 'target': sha}, indent=2))
        if previous:
            with (backup / 'database.dump').open('wb') as stream:
                compose(previous, 'exec', '-T', 'db', 'sh', '-c',
                        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc', stdout=stream)
            (backup / 'database.dump').chmod(0o600)
        try:
            compose(release, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120', 'db')
            compose(release, 'run', '--rm', '--no-deps', 'prepare')
            compose(release, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '300', 'db', 'backend')
            run(*ssh, f'activate {environment} {sha}', stdin=subprocess.DEVNULL)
            # Edge activation always checks local frontend/API, including in bootstrap.
            if not args.bootstrap:
                run('python3', release / 'scripts/check_production.py', '--url', target['public_url'])
            link = root / 'current.next'
            link.unlink(missing_ok=True)
            link.symlink_to(release)
            link.replace(root / 'current')
        except BaseException:
            try:
                if previous:
                    compose(previous, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '300', 'db', 'backend')
                else:
                    compose(release, 'stop', 'backend')
            finally:
                action = f'activate {environment} {previous_edge}' if previous_edge != 'none' else f'deactivate {environment} {sha}'
                run(*ssh, action, stdin=subprocess.DEVNULL)
            raise
        print(f'Deployed {environment} {sha}; backup: {backup}')


if __name__ == '__main__':
    main()
