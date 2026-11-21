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
deploy_spec = importlib.util.spec_from_file_location('deploy', SCRIPTS / 'deploy.py')
deploy = importlib.util.module_from_spec(deploy_spec)
deploy_spec.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def test_forced_command_rejects_shell_and_path_input(self):
        for value in ('sh', 'stage dev ../../etc', 'activate main aabbccd;id', 'current\nid',
                      'current other', 'stage ' + 'a' * 40, ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                edge.command(value)
        for environment in ('main', 'dev'):
            self.assertEqual(edge.command('stage ' + environment + ' ' + 'a' * 40), ('stage', environment, 'a' * 40))
            self.assertEqual(edge.command('current ' + environment), ('current', environment, None))

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
            env_root = root / 'environments' / 'dev'
            env_root.mkdir(parents=True)
            old, new = env_root / 'old', env_root / 'new'
            old.mkdir()
            new.mkdir()
            (new / 'compose.edge.yaml').touch()
            (env_root / 'current').symlink_to(old)
            failure = subprocess.CalledProcessError(1, 'compose')
            with patch.object(edge, 'ROOT', root), patch.object(edge, 'compose', side_effect=[failure, None]) as compose:
                with self.assertRaises(subprocess.CalledProcessError):
                    edge.activate('dev', new)
                self.assertEqual(compose.call_args_list[1].args[:2], ('dev', old))
                self.assertEqual((env_root / 'current').resolve(), old)

    def test_dev_activation_does_not_change_main_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for environment in ('main', 'dev'):
                env_root = root / 'environments' / environment
                (env_root / 'old').mkdir(parents=True)
                (env_root / 'current').symlink_to(env_root / 'old')
            new = root / 'environments/dev/new'
            new.mkdir()
            (new / 'compose.edge.yaml').touch()
            with patch.object(edge, 'ROOT', root), patch.object(edge, 'compose'), patch.object(edge, 'check'):
                edge.activate('dev', new)
            self.assertEqual((root / 'environments/dev/current').resolve(), new)
            self.assertEqual((root / 'environments/main/current').resolve(), root / 'environments/main/old')

    def test_compose_ports_images_and_projects_are_separate(self):
        configs = []
        for environment in ('main', 'dev'):
            with patch.object(edge.subprocess, 'run') as run:
                edge.compose(environment, Path('/releases/' + 'a' * 40), 'build', 'web')
                configs.append(run.call_args)
        self.assertNotEqual(configs[0].args[0][3], configs[1].args[0][3])
        for key in ('APP_IMAGE_TAG', 'APP_BASE_PATH', 'SITE_ADDRESS', 'TUNNEL_PORT', 'WEB_HEALTH_PORT'):
            self.assertNotEqual(configs[0].kwargs['env'][key], configs[1].kwargs['env'][key])
        for config in configs:
            self.assertEqual(config.kwargs['env']['WEB_BIND'], '127.0.0.1')

    def test_duplicate_origin_project_or_root_is_rejected(self):
        for dev_root, dev_project in (('/tmp/main', 'dev'), ('/tmp/dev', 'main')):
            config = {'environments': {'main': {'origin_root': '/tmp/main', 'origin_project': 'main'},
                                      'dev': {'origin_root': dev_root, 'origin_project': dev_project}}}
            with self.assertRaises(ValueError):
                deploy.settings(config, 'dev')

    def test_old_origin_image_tag_remains_usable_for_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory)
            self.assertEqual(deploy.image_tag(release, 'main'), release.name)
            (release / 'DEPLOYMENT_ENV').write_text('main\n')
            self.assertEqual(deploy.image_tag(release, 'main'), 'main-' + release.name)

    def test_gpu_opt_in_is_per_root_and_rollback_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'shared').mkdir()
            version = root / 'release'
            version.mkdir()
            (version / 'compose.gpu.yaml').touch()
            self.assertEqual(deploy.gpu_environment(root, version), {})
            device = root / 'shared/gpu-device'
            device.write_text('nvidia.com/gpu=0\n')
            self.assertEqual(deploy.gpu_environment(root, version), {'GPU_CDI_DEVICE': 'nvidia.com/gpu=0'})
            device.write_text('nvidia.com/gpu=all')
            with self.assertRaises(ValueError):
                deploy.gpu_environment(root, version)
            (version / 'compose.gpu.yaml').unlink()
            self.assertEqual(deploy.gpu_environment(root, version), {})

    def test_two_models_require_one_gpu(self):
        gpu = {'GPU_CDI_DEVICE': 'nvidia.com/gpu=0'}
        deploy.validate_e5_device('0', gpu)
        deploy.validate_e5_device('1', {})
        for device in ('all', '1'):
            with self.assertRaises(ValueError):
                deploy.validate_e5_device(device, gpu)

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
        self.assertEqual(check({'GITHUB_REF': 'refs/heads/dev',
                                'GITHUB_WORKFLOW_REF': 'GalimovKI/pentada-astr/.github/workflows/ci-cd.yml@refs/heads/dev'}), 0)
        for extra in ({'GITHUB_EVENT_NAME': 'pull_request'},
                      {'GITHUB_REF': 'refs/heads/feature'},
                      {'GITHUB_WORKFLOW_REF': 'another-workflow'},
                      {'GITHUB_JOB': 'untrusted'}, {'GITHUB_REPOSITORY': 'fork/repo'}):
            with self.subTest(extra=extra):
                self.assertNotEqual(check(extra), 0)
