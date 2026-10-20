"""実データを使用しない、成果物保管・削除の安全性試験。"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import artifact_cleanup as ac


class ArtifactCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'repo'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.write('.gitignore', '/build/\n/results/**/*.wav\n/results/**/*.trace\n')
        self.write('CMakeLists.txt', 'cmake_minimum_required(VERSION 3.20)\n')
        self.track('.gitignore', 'CMakeLists.txt')
        self.store = self.base / 'archives'
        self.idle = patch.object(ac, 'require_idle')
        self.idle.start()
        self.addCleanup(self.idle.stop)
        self.addCleanup(self.temp.cleanup)

    def write(self, name, value=b'data', days=10):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)
        old = time.time() - days * 86400
        os.utime(path, (old, old))
        return path

    def track(self, *names):
        subprocess.run(['git', '-C', str(self.root), 'add', '--', *names], check=True)

    def output(self, name='results/phase1/音 声.wav', data=None, days=10):
        if data is None:
            stream = io.BytesIO()
            with wave.open(stream, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b'\0\0\x01\x01' * 400)
            data = stream.getvalue()
        path = self.write(name, data, days)
        manifest = 'results/phase1/manifest.json'
        existing = json.loads((self.root / manifest).read_text()) if (self.root / manifest).exists() else []
        existing.append(dict(output_path=name, output_sha256=hashlib.sha256(data).hexdigest()))
        self.write(manifest, json.dumps(existing))
        return path

    def audit(self, **kw):
        result = ac.Audit(self.root, **kw)
        self.assertFalse(result.errors, result.errors)
        return result

    def category(self, name):
        return next(i['classification'] for i in self.audit().items if i['path'] == name)

    def archive(self, method='gzip'):
        result = ac.archive_phase(self.audit(), 'phase1', self.store, method)
        return Path(result['manifest'])

    def test_tracked_is_protected(self):
        name = 'results/phase1/table.csv'
        self.write(name)
        self.track(name)
        self.assertEqual(self.category(name), 'KEEP')

    def test_ignored_wav_is_detected_without_delete_permission(self):
        name = 'results/phase1/unknown.wav'
        self.write(name)
        row = next(i for i in self.audit().items if i['path'] == name)
        self.assertEqual(row['git_status'], 'ignored')
        self.assertEqual(row['classification'], 'REVIEW')

    def test_golden_and_independent_references_are_protected(self):
        for name in ('results/phase12/golden/raw/a.wav', 'build/phase57_frozen/product_reference',
                     'results/phase53/real/mix_input.wav', 'results/phase28/golden/a.wav'):
            self.write(name)
            self.assertEqual(self.category(name), 'KEEP')

    def test_manifest_roles_and_explicit_root(self):
        self.output()
        name = 'build/phase1/data.raw'
        self.write(name)
        self.write('results/phase1/PROVENANCE.json', json.dumps(dict(root=str(self.root / 'build/phase1'), reference=dict(path='data.raw'))))
        self.assertEqual(self.category(name), 'KEEP')
        self.assertEqual(self.category('results/phase1/音 声.wav'), 'ARCHIVE')
        self.assertTrue(self.audit().refs[name])

    def test_report_and_dry_run_change_nothing(self):
        self.output()
        before = self.tree()
        with patch.object(ac, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ac.main(['--report']), 0)
            self.assertEqual(ac.main(['--dry-run']), 0)
            self.assertEqual(ac.main([]), 0)
        self.assertEqual(before, self.tree())

    def tree(self):
        return {p.relative_to(self.root).as_posix(): (p.lstat().st_size, p.lstat().st_mtime_ns,
                hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else None)
                for p in self.root.rglob('*')}

    def test_wav_roundtrip_prune_and_restore(self):
        path = self.output()
        original = path.read_bytes()
        manifest = self.archive()
        self.assertEqual(path.read_bytes(), original)  # 圧縮だけでは削除しない。
        self.assertTrue(ac.verify_archive(manifest)['verification']['passed'])
        result = ac.prune_archive(self.audit(), manifest)
        self.assertEqual(result['files_deleted'], 1)
        self.assertFalse(path.exists())
        self.assertIn('actual_free_change_bytes', result)
        ac.restore_archive(self.root, manifest)
        self.assertEqual(path.read_bytes(), original)

    def test_csv_trace_empty_directory_and_metadata_roundtrip(self):
        path = self.output('results/phase1/表 data.csv', b'a,b\n1,2\n')
        trace = 'results/phase1/capture.trace'
        self.write(trace + '/Trace1.run/data.bin', b'123456' * 100)
        self.write(trace + '/metadata.json', '{}')
        (self.root / trace / 'empty').mkdir()
        handle = os.open(self.root / trace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            ac.set_xattr(handle, 'com.apple.metadata:test' if sys.platform == 'darwin' else 'user.test', b'attrs')
        finally:
            os.close(handle)
        self.write('results/phase1/trace_manifest.json', json.dumps(dict(output_trace=trace)))
        self.assertEqual(self.category(trace), 'ARCHIVE')
        manifest = self.archive()
        before = (self.root / trace / 'Trace1.run/data.bin').read_bytes()
        ac.prune_archive(self.audit(), manifest)
        ac.restore_archive(self.root, manifest)
        self.assertEqual((self.root / trace / 'Trace1.run/data.bin').read_bytes(), before)
        self.assertTrue((self.root / trace / 'empty').is_dir())
        self.assertEqual(path.read_bytes(), b'a,b\n1,2\n')
        handle = os.open(self.root / trace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertTrue(ac.xattrs(handle))
        finally:
            os.close(handle)

    def test_corrupt_archive_prevents_deletion(self):
        path = self.output()
        manifest = self.archive()
        m, payload = ac.load_manifest(manifest)
        with payload.open('r+b') as f:
            f.seek(20)
            f.write(b'corrupt!')
        with self.assertRaises(ac.SafetyError):
            ac.prune_archive(self.audit(), manifest)
        self.assertTrue(path.exists())

    def test_original_change_and_replacement_prevent_deletion(self):
        path = self.output()
        manifest = self.archive()
        original = path.read_bytes()
        path.write_bytes(original + b'changed')
        with self.assertRaises(ac.SafetyError):
            ac.prune_archive(self.audit(), manifest)
        path.unlink()
        path.write_bytes(original)
        with self.assertRaises(ac.SafetyError):
            ac.prune_archive(self.audit(), manifest)
        self.assertTrue(path.exists())

    def test_interrupted_archive_never_loses_source_or_completes(self):
        path = self.output()
        with patch.object(ac.tarfile.TarFile, 'addfile', side_effect=OSError('injected disk error')):
            with self.assertRaises(OSError):
                self.archive()
        self.assertTrue(path.exists())
        self.assertFalse(list(self.store.glob('*/archive_manifest.json')))
        self.assertTrue(list(self.store.glob('*.partial')))

    def test_confirmation_required(self):
        self.output()
        before = self.tree()
        with patch.object(ac, 'ROOT', self.root), contextlib.redirect_stderr(io.StringIO()):
            for mode in ('--archive', '--prune', '--restore'):
                self.assertEqual(ac.main([mode, '--phase', 'phase1']), 2)
        self.assertEqual(before, self.tree())

    def test_links_and_traversal_never_access_outside(self):
        external = self.base / 'external'
        external.mkdir()
        (external / 'data.wav').write_bytes(b'outside')
        (self.root / 'results').mkdir()
        (self.root / 'results/phase1').symlink_to(external, target_is_directory=True)
        audit = self.audit()
        self.assertEqual(audit.items[0]['classification'], 'REVIEW')
        for name in ('../external/data.wav', '/etc/passwd', 'results/phase1/../../bad', 'build/.git/file'):
            with self.assertRaises(ac.SafetyError):
                ac.target_relative(name)
        with self.assertRaises(OSError):
            ac.file_hash(self.root, 'results/phase1/data.wav')
        self.assertEqual((external / 'data.wav').read_bytes(), b'outside')

    def test_idempotent_archive_prune_and_refuse_restore_overwrite(self):
        path = self.output()
        first = self.archive()
        self.assertEqual(self.archive(), first)
        self.assertEqual(len(list(self.store.glob('phase1_*'))), 1)
        with self.assertRaises(ac.SafetyError):
            ac.restore_archive(self.root, first)
        self.assertTrue(path.exists())
        ac.prune_archive(self.audit(), first)
        result = ac.prune_archive(self.audit(), first)
        self.assertEqual(result['status'], 'ALREADY_ABSENT')

    def test_low_space_and_permission_failure(self):
        path = self.output()
        usage = shutil.disk_usage(self.root)
        with patch.object(ac.shutil, 'disk_usage', return_value=type(usage)(usage.total, usage.used, 0)):
            with self.assertRaises(ac.SafetyError):
                self.archive()
        self.assertFalse(list(self.store.glob('*partial')))
        with patch.object(ac, 'tar_writer', side_effect=PermissionError('injected')):
            with self.assertRaises(PermissionError):
                self.archive()
        self.assertTrue(path.exists())

    def test_nonascii_and_spaces_in_external_restore_directory(self):
        path = self.output('results/phase1/日本語 音声.wav')
        manifest = self.archive()
        destination = self.base / '復元 場所'
        ac.restore_archive(self.root, manifest, destination)
        self.assertEqual((destination / path.relative_to(self.root)).read_bytes(), path.read_bytes())

    def test_change_during_compression_is_detected(self):
        path = self.output()
        add = ac.tarfile.TarFile.addfile
        def changed(archive, info, fileobj=None):
            result = add(archive, info, fileobj)
            if fileobj:
                path.write_bytes(b'changed while compression')
            return result
        with patch.object(ac.tarfile.TarFile, 'addfile', changed):
            with self.assertRaises(ac.SafetyError):
                self.archive()
        self.assertEqual(path.read_bytes(), b'changed while compression')
        self.assertFalse(list(self.store.glob('phase1_*')))

    def test_reference_hash_mismatch_and_new_protection(self):
        path = self.output()
        self.write('results/phase1/manifest.json', json.dumps(dict(output_path=str(path), output_sha256='0' * 64)))
        with self.assertRaises(ac.SafetyError):
            self.archive()
        self.write('results/phase1/manifest.json', json.dumps(dict(output_path=str(path), output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
        manifest = self.archive()
        self.write('results/phase1/REPORT.md', '未解決のNO-GO証拠')
        with self.assertRaises(ac.SafetyError):
            ac.prune_archive(self.audit(), manifest)
        self.assertTrue(path.exists())

    def test_recent_unknown_and_prune_age_policy(self):
        self.output(days=1)
        self.assertEqual(self.category('results/phase1/音 声.wav'), 'KEEP')
        self.write('build/CMakeCache.txt', 'CMAKE_BUILD_TYPE=Release')
        name = 'build/CMakeFiles/test.dir/file.cpp.o'
        self.write(name, days=40)
        self.assertEqual(self.category(name), 'PRUNE')
        self.write('results/phase1/unknown.pcm', days=90)
        self.assertEqual(self.category('results/phase1/unknown.pcm'), 'REVIEW')

    def test_regenerable_requires_explicit_scope_and_archive_opt_in(self):
        self.write('build/CMakeCache.txt', 'CMAKE_BUILD_TYPE=Release')
        name = 'build/CMakeFiles/test.dir/file.cpp.o'
        self.write(name, days=40)
        with self.assertRaises(ac.SafetyError):
            ac.archive_phase(self.audit(), None, self.store, 'gzip', paths=[name])
        result = ac.archive_phase(self.audit(), None, self.store, 'gzip', True, [name])
        self.assertTrue((self.root / name).exists())
        ac.prune_archive(self.audit(), result['manifest'])
        self.assertFalse((self.root / name).exists())

    def test_missing_manifest_and_incomplete_manifest(self):
        with self.assertRaises(OSError):
            ac.verify_archive(self.base / 'missing.json')
        bad = self.base / 'bad.json'
        bad.write_text(json.dumps(dict(schema=ac.SCHEMA, status='INCOMPLETE')))
        with self.assertRaises(ac.SafetyError):
            ac.verify_archive(bad)

    def test_partial_directory_never_counts_as_complete(self):
        self.output()
        manifest = self.archive()
        partial = self.store / 'copied.partial'
        shutil.copytree(manifest.parent, partial)
        with self.assertRaises(ac.SafetyError):
            ac.verify_archive(partial / manifest.name)

    def test_fail_scope_and_missing_reference_are_reported(self):
        path = self.output()
        self.write('results/phase1/result.json', '{"PASS":false}')
        self.assertEqual(self.category(path.relative_to(self.root).as_posix()), 'REVIEW')
        self.write('results/phase1/PROVENANCE.json', json.dumps(dict(input_path='build/phase1/missing.wav', input_sha256='1' * 64)))
        self.assertEqual(self.audit().missing_references[0]['path'], 'build/phase1/missing.wav')
        self.assertEqual(len(self.audit().missing_references), 1)

    def test_manifest_path_traversal_is_rejected(self):
        self.output()
        manifest = self.archive()
        m = json.loads(manifest.read_text())
        m['entries'][0]['path'] = '../outside.wav'
        manifest.write_text(json.dumps(m))
        with self.assertRaises(ac.SafetyError):
            ac.verify_archive(manifest)

    def test_lsof_failure_and_actual_open_file(self):
        path = self.output()
        self.idle.stop()
        try:
            with patch.object(ac.shutil, 'which', return_value=None):
                with self.assertRaises(ac.SafetyError):
                    ac.require_idle(self.root, [path.relative_to(self.root).as_posix()])
            if shutil.which('lsof'):
                with path.open('rb'):
                    with self.assertRaises(ac.SafetyError):
                        ac.require_idle(self.root, [path.relative_to(self.root).as_posix()])
        finally:
            self.idle.start()

    def test_lock_and_open_file_detection(self):
        with ac.exclusive(self.root):
            with self.assertRaises(ac.SafetyError):
                with ac.exclusive(self.root):
                    pass
        self.idle.stop()
        self.write('results/phase1/data.csv')
        try:
            with patch.object(ac.shutil, 'which', return_value='/fake/lsof'), patch.object(ac.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'p123\nnfile\n', '')):
                with self.assertRaises(ac.SafetyError):
                    ac.require_idle(self.root, ['results/phase1/data.csv'])
        finally:
            self.idle.start()

    def test_trace_added_member_prevents_prune(self):
        self.write('results/phase1/a.trace/data', b'a')
        self.write('results/phase1/manifest.json', json.dumps(dict(output_trace='results/phase1/a.trace')))
        manifest = self.archive()
        self.write('results/phase1/a.trace/new', b'new')
        with self.assertRaises(ac.SafetyError):
            ac.prune_archive(self.audit(), manifest)
        self.assertTrue((self.root / 'results/phase1/a.trace/data').exists())

    def test_failure_after_staging_rolls_back(self):
        path = self.output()
        manifest = self.archive()
        verify = ac.verify_archive
        count = 0
        def fail_second(*a, **kw):
            nonlocal count
            count += 1
            if count == 2:
                raise ac.SafetyError('injected archive change after staging')
            return verify(*a, **kw)
        with patch.object(ac, 'verify_archive', side_effect=fail_second):
            with self.assertRaises(ac.SafetyError):
                ac.prune_archive(self.audit(), manifest)
        self.assertTrue(path.exists())

    def test_receipt_permission_failure_prevents_any_deletion(self):
        path = self.output()
        manifest = self.archive()
        with patch.object(ac, 'write_json', side_effect=PermissionError('receipt denied')):
            with self.assertRaises(PermissionError):
                ac.prune_archive(self.audit(), manifest)
        self.assertTrue(path.exists())

    def test_recreated_source_path_is_preserved_and_prune_stops(self):
        path = self.output()
        manifest = self.archive()
        rename = ac.os.rename
        def recreate(*a, **kw):
            rename(*a, **kw)
            if not path.exists():
                path.write_bytes(b'new producer output')
        with patch.object(ac.os, 'rename', side_effect=recreate):
            with self.assertRaises(ac.SafetyError):
                ac.prune_archive(self.audit(), manifest)
        self.assertEqual(path.read_bytes(), b'new producer output')
        self.assertTrue(list((self.root / 'build').glob('.artifact_cleanup_transaction_*')))

    def test_malformed_reference_table_stops_mutations_with_report(self):
        path = self.output()
        self.write('results/phase1/manifest.csv', 'output\nresults/phase1/file.wav,extra\n')
        audit = ac.Audit(self.root)
        self.assertTrue(audit.errors)
        self.assertTrue(audit.summary()['errors'])
        with self.assertRaises(ac.SafetyError):
            ac.archive_phase(audit, 'phase1', self.store, 'gzip')
        self.assertTrue(path.exists())

    def test_vendored_sample_is_counted_but_not_used_as_evidence(self):
        self.output()
        name = 'build/phase1/plot_dependencies/lib/sample.csv'
        self.write(name, 'output\nresults/phase1/file.wav,extra\n')
        audit = self.audit()
        self.assertIn(name, audit.files)
        self.assertEqual(next(i['classification'] for i in audit.items if i['path'] == 'results/phase1/音 声.wav'), 'ARCHIVE')

    def test_running_phase_is_held_without_path_fields(self):
        path = self.output()
        self.write('results/phase1/progress.json', '{"status":"RUNNING"}')
        self.assertEqual(self.category(path.relative_to(self.root).as_posix()), 'REVIEW')

    def test_unresolved_trace_child_cannot_be_archived(self):
        self.write('results/phase1/a.trace/data.bin', b'data')
        self.write('results/phase1/a.trace/analysis/state.json', '{"status":"RUNNING"}')
        self.write('results/phase1/manifest.json', json.dumps(dict(output_trace='results/phase1/a.trace')))
        self.assertEqual(self.category('results/phase1/a.trace'), 'REVIEW')

    def test_reference_alias_is_protected(self):
        path = self.output()
        self.write('results/phase1/comparison.json', json.dumps(dict(ref=path.relative_to(self.root).as_posix())))
        self.assertEqual(self.category(path.relative_to(self.root).as_posix()), 'KEEP')

    def test_phase_letter_suffix_and_archive_selection(self):
        self.output('results/phase9a/output.wav')
        audit = self.audit()
        self.assertEqual(ac.phase_of('results/phase9a/output.wav'), 'phase9a')
        result = ac.archive_phase(audit, 'phase9a', self.store, 'gzip')
        self.assertEqual(ac.verify_archive(result['manifest'])['phase'], 'phase9a')

    @unittest.skipUnless(shutil.which('zstd'), 'zstd未導入')
    def test_zstd_roundtrip(self):
        path = self.output()
        manifest = self.archive('zstd')
        destination = self.base / 'restored'
        ac.restore_archive(self.root, manifest, destination)
        self.assertEqual((destination / path.relative_to(self.root)).read_bytes(), path.read_bytes())


if __name__ == '__main__':
    unittest.main()
