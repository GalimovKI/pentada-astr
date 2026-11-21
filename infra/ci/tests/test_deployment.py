import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('edge', SCRIPTS / 'edge_receive.py')
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)


class DeploymentTests(unittest.TestCase):
    def test_forced_command_rejects_shell_and_path_input(self):
        for value in ('sh', 'stage ../../etc', 'activate aabbccd;id', 'current\nid', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                edge.command(value)
        self.assertEqual(edge.command('stage ' + 'a' * 40), ('stage', 'a' * 40))

    def archive(self, name, kind=tarfile.REGTYPE):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = '/etc'
            archive.addfile(member, io.BytesIO())
        data.seek(0)
        return tarfile.open(fileobj=data, mode='r|gz')

    def test_archive_cannot_escape_release_directory(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/escape', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('hardlink', tarfile.LNKTYPE)]:
            with tempfile.TemporaryDirectory() as directory:
                with self.archive(name, kind) as archive, self.assertRaises(ValueError):
                    edge.extract(archive, Path(directory))

    def test_regular_archive_extracts(self):
        with tempfile.TemporaryDirectory() as directory, self.archive('src/file') as archive:
            edge.extract(archive, Path(directory))
            self.assertTrue((Path(directory) / 'src/file').is_file())

    def test_failed_edge_health_restores_previous_container_and_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old, new = root / 'old', root / 'new'
            old.mkdir()
            new.mkdir()
            (new / 'compose.edge.yaml').touch()
            (root / 'current').symlink_to(old)
            failure = subprocess.CalledProcessError(1, 'compose')
            with patch.object(edge, 'ROOT', root), patch.object(edge, 'compose', side_effect=[failure, None]) as compose:
                with self.assertRaises(subprocess.CalledProcessError):
                    edge.activate(new)
                self.assertEqual(compose.call_args_list[1].args[0], old)
                self.assertEqual((root / 'current').resolve(), old)

    def test_runner_guard_blocks_prs_branches_and_other_workflows(self):
        env = {**os.environ, 'GITHUB_REPOSITORY': 'GalimovKI/pentada-astr',
               'GITHUB_REF': 'refs/heads/main', 'GITHUB_JOB': 'deploy',
               'GITHUB_EVENT_NAME': 'push',
               'GITHUB_WORKFLOW_REF': 'GalimovKI/pentada-astr/.github/workflows/ci-cd.yml@refs/heads/main'}
        def check(extra):
            return subprocess.run(['bash', str(SCRIPTS / 'runner-guard.sh')],
                                  env={**env, **extra}, capture_output=True).returncode
        self.assertEqual(check({}), 0)
        self.assertEqual(check({'GITHUB_EVENT_NAME': 'workflow_dispatch'}), 0)
        for extra in ({'GITHUB_EVENT_NAME': 'pull_request'},
                      {'GITHUB_REF': 'refs/heads/feature'},
                      {'GITHUB_WORKFLOW_REF': 'another-workflow'},
                      {'GITHUB_JOB': 'untrusted'}, {'GITHUB_REPOSITORY': 'fork/repo'}):
            with self.subTest(extra=extra):
                self.assertNotEqual(check(extra), 0)
