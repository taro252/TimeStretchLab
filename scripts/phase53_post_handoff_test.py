"""Deterministic post-handoff faults; detecting invalid evidence is test success."""
import copy
import csv
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from phase52_verdict import NUMERIC
from phase53_sessions import (CSV_COLUMNS, DENSITY_CONVERSION_REASON, convert_density_units,
                              verify_run)


def write_csv(path, name, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS[name].split(','), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


class PostHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='phase53_post_')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run'
        self.run.mkdir()
        pcm = struct.pack('<f', .1) * 100
        fmt = struct.pack('<HHIIHH', 3, 1, 48000, 192000, 4, 32)
        self.reference = self.root / 'reference.wav'
        self.reference.write_bytes(b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
                                   struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', len(pcm)) + pcm)
        self.row = dict.fromkeys(NUMERIC, '0')
        self.row.update(output_frames='100', produced_frames='100', consumed_frames='100',
                        presented_frames='100', sample_rate='48000', callback_allocations_measured='1',
                        raw_pcm_sha256=hashlib.sha256(pcm).hexdigest(), state='Ended', reason='EOS',
                        eos='1', AUDIO_QUALITY='PASS', MEASUREMENT_QUALITY='PASS', session='1',
                        initial='.4', preset='candidate', channels='1', generated_frames='100',
                        published_frames='100', device_raw_frames='100', hash_frames='100',
                        hash_scope='fifo_published_raw_float32_interleaved_prefix', start_state='Playing',
                        callback_rows='1', callback_calls='1', worker_rows='1', plan_rows='2',
                        operation_rows='2', worker_error='', native_error='', concurrent_renders='0')
        self.plans = []
        self.ops = []
        for generation in (1, 2):
            plan = dict.fromkeys(CSV_COLUMNS['plans.csv'].split(','), '0')
            plan.update(generation=str(generation), requested_output='10', requested_input='1',
                        **{'from': '.4', 'target': '2'}, fence='20', prepared='15', published='10',
                        applied_frame='2', applied_output=str(generation * 20),
                        completion_output=str(generation * 20 + 10), density_input=str(generation + 2),
                        map_bytes='100', plan_ms='1.25', state_preserved='1')
            self.plans.append(plan)
            self.ops.append(dict(id=str(generation), session='1', generation=str(generation),
                                 observed_ns='1', sent_ns='2', completed_ns='3', target='2',
                                 status='Completed', apply_output=plan['applied_output'],
                                 complete_output=plan['completion_output']))
        cb = dict.fromkeys(CSV_COLUMNS['callbacks.csv'].split(','), '0')
        cb.update(sequence='1', epoch='1', wanted='100', received='100', requested='100', host_ns='1', flags='3')
        worker = dict.fromkeys(CSV_COLUMNS['workers.csv'].split(','), '0')
        worker.update(cycle='1', frames='100', publication_interval_s='-1')
        write_csv(self.run/'callbacks.csv', 'callbacks.csv', [cb])
        write_csv(self.run/'workers.csv', 'workers.csv', [worker])
        (self.run/'sessions.csv').write_text('session,folder\n1,.\n')
        (self.run/'lifecycle.txt').write_text('remaining_actions=0\nrestarts=0\n')
        (self.run/'actions.csv').write_text('planned_seconds,type,result\n')
        self.save()
        self.corrected = self.root / 'plans_samples.csv'
        convert_density_units(self.run/'plans.csv', self.corrected, self.row, self.ops)

    def save(self):
        (self.run/'summary.txt').write_text(''.join(f'{key}={value}\n' for key, value in self.row.items()))
        write_csv(self.run/'plans.csv', 'plans.csv', self.plans)
        write_csv(self.run/'operations.csv', 'operations.csv', self.ops)

    def verify(self, corrected=True, original=None, reason=DENSITY_CONVERSION_REASON, legacy=False):
        return verify_run(self.run, self.reference, 0, reference_override=self.reference,
                          plan_override=self.corrected if corrected else None, original=original,
                          correction_reason=reason if corrected else None, legacy=legacy)

    def assert_fail(self, result):
        self.assertEqual(result['VERDICT'], 'FAIL')
        self.assertEqual(result['CSV_INTEGRITY'], 'FAIL')
        self.assertEqual(result['MEASUREMENT_QUALITY'], 'FAIL')

    def test_normal_original_and_correction(self):
        self.assertEqual(self.verify(False)['VERDICT'], 'PASS')
        result = self.verify()
        self.assertEqual(result['VERDICT'], 'PASS')
        audit = result['evidence']['plan_csv']
        self.assertEqual(audit['original']['CSV_INTEGRITY'], 'PASS')
        self.assertEqual(audit['corrected']['CSV_INTEGRITY'], 'PASS')
        conversion = audit['conversion']
        self.assertEqual(conversion['PERMITTED_CONVERSION'], 'PASS')
        self.assertEqual(conversion['original_sha256'], hashlib.sha256((self.run/'plans.csv').read_bytes()).hexdigest())
        self.assertEqual(conversion['corrected_sha256'], hashlib.sha256(self.corrected.read_bytes()).hexdigest())
        self.assertEqual(conversion['reason'], DENSITY_CONVERSION_REASON)
        self.assertNotEqual(conversion['original_sha256'], conversion['corrected_sha256'])

    def test_original_truncation_not_hidden(self):
        path = self.run/'plans.csv'
        path.write_bytes(path.read_bytes()[:-1])
        result = self.verify()
        self.assert_fail(result)
        audit = result['evidence']['plan_csv']
        self.assertEqual(audit['original']['CSV_INTEGRITY'], 'FAIL')
        self.assertEqual(audit['corrected']['CSV_INTEGRITY'], 'PASS')
        with self.assertRaises(ValueError):
            convert_density_units(path, self.root/'refused.csv', self.row, self.ops)
        self.assertFalse((self.root/'refused.csv').exists())

    def test_correction_cli_refuses_truncated_original(self):
        path = self.run/'plans.csv'
        path.write_bytes(path.read_bytes()[:-1])
        original = dict(self.row, source='fixture', seconds='1', exit=0, VERDICT='PASS')
        (self.run/'validation.json').write_text(json.dumps(original))
        output = self.root/'correction_review'
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('phase52_recheck_controls.py')),
                                 '--root', str(self.root), '--output', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        saved = json.loads((output/'summary.json').read_text())[0]
        self.assert_fail(saved)
        self.assertEqual(saved['original_integrity']['plan_csv']['original']['CSV_INTEGRITY'], 'FAIL')
        self.assertEqual(saved['original_integrity']['plan_csv']['original']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertFalse((output/'run/plans_samples.csv').exists())
        self.assertEqual(path.read_bytes()[-1:], b'1')

    def test_original_row_shortage(self):
        self.plans.pop()
        self.save()
        self.assert_fail(self.verify())

    def test_legacy_missing_row_detected_from_operations(self):
        self.plans.pop()
        self.row.pop('plan_rows')
        self.save()
        self.assert_fail(self.verify(legacy=True))

    def test_legacy_cancelled_plan_count_cannot_be_invented(self):
        self.row.update(reason='User', state='Stopped', eos='0')
        self.ops[0].update(status='Cancelled', apply_output='0', complete_output='0')
        self.save()
        self.assertEqual(self.verify(False)['VERDICT'], 'PASS')
        self.row.pop('plan_rows')
        self.save()
        self.assert_fail(self.verify(False, legacy=True))

    def test_original_generation_gap(self):
        self.plans[1]['generation'] = '3'
        self.save()
        self.assert_fail(self.verify())

    def test_original_nonfinite(self):
        for value in ('NaN', 'Inf', '-Inf'):
            with self.subTest(value=value):
                self.plans[0]['plan_ms'] = value
                self.save()
                self.assert_fail(self.verify())

    def test_original_header_column_count(self):
        path = self.run/'plans.csv'
        original = path.read_text()
        for contents in (original.replace('plan_ms,', 'other_ms,'), original.replace('plan_ms,', 'plan_ms,extra,'),
                         original.replace('1.25,1\n', '1.25,1,extra\n'), original.replace('1.25,1\n', '1.25\n')):
            with self.subTest(contents=contents[:80]):
                path.write_text(contents)
                self.assert_fail(self.verify())

    def test_originating_failures_retained(self):
        for key in ('AUDIO_QUALITY', 'MEASUREMENT_QUALITY', 'CSV_INTEGRITY'):
            with self.subTest(key=key):
                result = self.verify(original={key: 'FAIL', 'PCM_CORRECTNESS': 'FAIL'})
                self.assertEqual(result[key], 'FAIL')
                self.assertEqual(result['VERDICT'], 'FAIL')

    def test_closed_session_original_failure_retained(self):
        self.assert_fail(self.verify(original={'sessions': [{'folder': '.', 'CSV_INTEGRITY': 'FAIL'}]}))

    def test_corrected_corruption(self):
        self.corrected.write_bytes(self.corrected.read_bytes()[:-1])
        result = self.verify()
        self.assert_fail(result)
        self.assertEqual(result['evidence']['plan_csv']['original']['CSV_INTEGRITY'], 'PASS')
        self.assertEqual(result['evidence']['plan_csv']['corrected']['CSV_INTEGRITY'], 'FAIL')

    def test_only_density_unit_conversion_permitted(self):
        records = copy.deepcopy(self.plans)
        for record in records: record['density_input'] = str(int(record['density_input']) * 1024)
        records[0]['plan_ms'] = '2.25'
        write_csv(self.corrected, 'plans.csv', records)
        self.assert_fail(self.verify())

    def test_wrong_factor_and_no_explicit_reason(self):
        self.assert_fail(self.verify(reason=None))
        records = copy.deepcopy(self.plans)
        for record in records: record['density_input'] = str(int(record['density_input']) * 512)
        write_csv(self.corrected, 'plans.csv', records)
        self.assert_fail(self.verify())

    def test_no_overwrite_of_correction(self):
        before = self.corrected.read_bytes()
        with self.assertRaises(FileExistsError):
            convert_density_units(self.run/'plans.csv', self.corrected, self.row, self.ops)
        self.assertEqual(self.corrected.read_bytes(), before)

    def test_user_stop_and_route_cancellation(self):
        for reason in ('User', 'RouteChanged'):
            with self.subTest(reason=reason):
                self.row.update(reason=reason, state='Stopped', eos='0', route_stopped='1' if reason=='RouteChanged' else '0')
                self.ops[1]['status'] = 'Cancelled'
                self.save()
                self.assertEqual(self.verify(False)['VERDICT'], 'PASS')

    def test_terminal_latest_wins_duplicate_configured_rejected(self):
        for status in ('Replaced', 'Duplicate', 'Configured', 'Rejected', 'Cancelled'):
            with self.subTest(status=status):
                extra = dict(self.ops[0], id='3', generation='0', status=status, sent_ns='0',
                             completed_ns='0', apply_output='0', complete_output='0')
                # Completion order can differ from operation ID order.
                self.ops = [extra] + [op for op in self.ops if op['id'] != '3']
                self.row['operation_rows'] = '3'
                self.save()
                self.assertEqual(self.verify(False)['VERDICT'], 'PASS')

    def test_rejected_generation_gap_is_legitimate(self):
        self.plans[1]['generation'] = '3'
        self.ops[1].update(id='3', generation='3')
        self.ops.append(dict(self.ops[0], id='2', generation='2', status='Rejected', completed_ns='0',
                             apply_output='0', complete_output='0'))
        self.row['operation_rows'] = '3'
        self.save()
        self.assertEqual(self.verify(False)['VERDICT'], 'PASS')

    def test_nonterminal_and_unknown_at_every_end(self):
        for reason in ('EOS', 'User', 'RouteChanged'):
            for status in ('Pending', 'Submitted', 'Applied', 'Unknown', ''):
                with self.subTest(reason=reason, status=status):
                    self.row.update(reason=reason, state='Ended' if reason=='EOS' else 'Stopped',
                                    eos='1' if reason=='EOS' else '0', route_stopped='1' if reason=='RouteChanged' else '0')
                    self.ops[0]['status'] = status
                    self.save()
                    self.assert_fail(self.verify(False))

    def test_operation_id_session_generation(self):
        saved = copy.deepcopy(self.ops)
        for key, value in (('id', '0'), ('id', '2'), ('id', '3'), ('session', '0'), ('session', '2'),
                           ('generation', '0'), ('generation', '2'), ('generation', '1.5'),
                           ('target', '.75'), ('complete_output', '60')):
            with self.subTest(key=key, value=value):
                self.ops = copy.deepcopy(saved)
                self.ops[0][key] = value
                self.save()
                self.assert_fail(self.verify(False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
