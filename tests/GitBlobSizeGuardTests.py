"""隔離した一時Gitで境界値・履歴途中・remote既存blobを検証する。"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts/check_git_blob_sizes.py'


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ts-git-size-test-')
        self.repo = pathlib.Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Size guard fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'gc.auto=0',
                                        *args], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def guard(self, *args, input=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo,
                              input=input, text=True, capture_output=True)

    def file(self, size):
        with (self.repo / 'fixture.bin').open('wb') as f:
            f.truncate(size)
        self.git('add', 'fixture.bin')

    def commit(self):
        self.git('-c', 'commit.gpgSign=false', 'commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def test_threshold_uses_staged_blob(self):
        self.file(49_999_999)
        self.assertEqual(self.guard('staged').returncode, 0)
        self.file(50_000_000)
        result = self.guard('staged')
        self.assertEqual(result.returncode, 1)
        self.assertIn('50000000', result.stderr)
        # 作業ファイルを小さくしても、indexの大きなblobを検出する。
        (self.repo / 'fixture.bin').write_bytes(b'small')
        self.assertEqual(self.guard('staged').returncode, 1)

    def test_oversized_intermediate_commit(self):
        (self.repo / 'small').write_text('base')
        self.git('add', 'small')
        base = self.commit()
        self.file(50_000_000)
        self.commit()
        self.git('rm', 'fixture.bin')
        self.commit()
        self.assertEqual(self.guard('staged').returncode, 0)
        self.assertEqual(self.guard('history', '--base', base).returncode, 1)

    def test_remote_existing_history_is_not_new(self):
        self.file(50_000_000)
        base = self.commit()
        remote = pathlib.Path(self.tmp.name) / 'remote.git'
        subprocess.run(['git', 'clone', '--bare', '-q', str(self.repo), str(remote)], check=True)
        (self.repo / 'small').write_text('new')
        self.git('add', 'small')
        tip = self.commit()
        # 新しいブランチでもremoteが広告する既存履歴を除外する。
        line = f'refs/heads/new {tip} refs/heads/new {"0" * 40}\n'
        self.assertEqual(self.guard('pre-push', '--remote', str(remote), input=line).returncode, 0)
        self.assertEqual(self.guard('history', '--base', base).returncode, 0)

    def test_new_history_and_remote_errors_fail_closed(self):
        self.file(50_000_000)
        tip = self.commit()
        remote = pathlib.Path(self.tmp.name) / 'empty.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        line = f'refs/heads/new {tip} refs/heads/new {"0" * 40}\n'
        self.assertEqual(self.guard('pre-push', '--remote', str(remote), input=line).returncode, 1)
        self.assertEqual(self.guard('pre-push', '--remote', str(remote / 'missing'), input=line).returncode, 2)
        self.assertEqual(self.guard('pre-push', '--remote', str(remote), input='invalid').returncode, 2)

    def test_ref_delete_sends_no_new_objects(self):
        line = f'(delete) {"0" * 40} refs/heads/old {"1" * 40}\n'
        self.assertEqual(self.guard('pre-push', '--remote', 'unused', input=line).returncode, 0)


if __name__ == '__main__':
    unittest.main()
