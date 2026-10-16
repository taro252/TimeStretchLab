"""Check trace references, interval clipping and explicit observation gaps."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from phase58_fix_trace_analyze import IntervalIndex, classify, overlap, table, complete_export


def cell(value, fmt=None):
    return dict(value=str(value), fmt=str(value) if fmt is None else fmt)


def state(start, duration, name):
    return dict(start=cell(start), duration=cell(duration), state=cell(name), priority=cell(37),
                note=cell('unknown'), summary=cell(name), **{'preempted-by-thread':cell('unknown'), 'core':cell(0)})


class TraceTests(unittest.TestCase):
    def test_incomplete_export_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.xml'
            path.write_text('<trace-query-result><node><row>')
            self.assertFalse(complete_export(path))
            path.write_text('<trace-query-result><node/></trace-query-result>\n')
            self.assertTrue(complete_export(path))
    def test_interval_clipping_and_gaps(self):
        states=IntervalIndex([state(0, 4, 'Running'), state(6, 4, 'Preempted')])
        r=classify(2, 9, states, IntervalIndex([]), IntervalIndex([]))
        self.assertAlmostEqual(r['state_seconds']['Running'], 2e-9)
        self.assertAlmostEqual(r['state_seconds']['Preempted'], 3e-9)
        self.assertAlmostEqual(r['unobserved_s'], 2e-9)
        self.assertEqual(overlap(0, 4, 4, 8), 0)

    def test_nested_syscalls_are_not_lost_by_index(self):
        states=IntervalIndex([state(0, 10, 'Blocked')])
        outer=dict(start=cell(0), duration=cell(10), call=cell('outer'))
        inner=dict(start=cell(5), duration=cell(1), call=cell('inner'))
        r=classify(6, 7, states, IntervalIndex([outer, inner]), IntervalIndex([]))
        self.assertEqual([x['name'] for x in r['syscalls']], ['outer'])

    def test_xml_references_and_thread_filter(self):
        xml='''<trace-query-result><node><schema><col><mnemonic>start</mnemonic></col><col><mnemonic>thread</mnemonic></col></schema>
        <row><start-time id="1">0</start-time><thread id="2"><tid id="3">42</tid><process id="4"><pid id="5">7</pid></process></thread></row>
        <row><start-time id="6">10</start-time><thread ref="2"/></row>
        <row><start-time ref="6"/><thread id="7"><tid>43</tid><process ref="4"/></thread></row></node></trace-query-result>'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.xml';path.write_text(xml)
            rows=table(path, {42})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['thread']['tid'], 42)
        self.assertEqual(rows[1]['thread']['pid'], 7)
        self.assertEqual(rows[1]['start']['value'], '10')


if __name__ == '__main__':
    unittest.main()
