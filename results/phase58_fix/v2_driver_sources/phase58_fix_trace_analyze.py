"""Correlate Instruments thread states with pipeline stages and FIFO callbacks.

Trace states are observations. Wall minus CPU remains unclassified unless the
trace actually covers that interval. No estimated runnable time fills gaps.
"""
import argparse
import bisect
import collections
import csv
import gzip
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from phase58_fix_repeat import sha

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ('time-info', 'thread-state', 'syscall', 'virtual-memory')


def complete_export(path):
    if not path.exists() or path.stat().st_size<25:
        return False
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-128))
        return f.read().rstrip().endswith(b'</trace-query-result>')


def table(path, tids=None):
    root = ET.parse(path).getroot()
    definitions = {e.get('id'): e for e in root.iter() if e.get('id')}

    def resolve(e):
        return definitions[e.get('ref')] if e.get('ref') else e

    def nested(e, tag):
        e = resolve(e)
        if e.tag == tag:
            return e
        for child in e:
            result = nested(child, tag)
            if result is not None:
                return result
        return None

    def value(e):
        e = resolve(e)
        tid, pid = nested(e, 'tid'), nested(e, 'pid')
        result = dict(value=e.text, fmt=e.get('fmt', e.text), tag=e.tag)
        if tid is not None:
            result['tid'] = int(tid.text)
        if pid is not None:
            result['pid'] = int(pid.text)
        if e.tag == 'tagged-backtrace':
            result['frames'] = [resolve(f).get('name', resolve(f).get('addr', 'unknown')) for f in e]
        return result

    schema = root.find('.//schema')
    if schema is None:
        return []
    columns = [e.text for e in schema.iter('mnemonic')]
    selected = []
    thread_index = columns.index('thread') if 'thread' in columns else None
    for row in root.iter('row'):
        cells = list(row)
        if tids is not None and thread_index is not None:
            tid = nested(cells[thread_index], 'tid')
            if tid is None or int(tid.text) not in tids:
                continue
        selected.append({name: value(e) for name, e in zip(columns, cells)})
    return selected


def number(row, name, default=0):
    value = row.get(name, {}).get('value')
    return float(value) if value is not None else default


def overlap(a, b, c, d):
    return max(0, min(b, d)-max(a, c))


class IntervalIndex:
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r:number(r, 'start'))
        self.starts = [number(r, 'start') for r in self.rows]
        self.ends = []
        high = -1
        for row in self.rows:
            high = max(high, number(row, 'start')+number(row, 'duration'))
            self.ends.append(high)

    def query(self, start, end):
        return self.rows[bisect.bisect_right(self.ends, start):bisect.bisect_left(self.starts, end)]


def classify(start, end, states, syscalls, faults):
    durations = collections.defaultdict(float)
    longest = {}
    for row in states.query(start, end):
        length = overlap(start, end, number(row, 'start'), number(row, 'start')+number(row, 'duration'))
        if not length:
            continue
        state = row['state']['fmt']
        durations[state] += length*1e-9
        if length > longest.get('overlap_ns', 0):
            longest = dict(overlap_ns=length, state=state, priority=row['priority']['fmt'],
                           note=row['note']['fmt'], summary=row['summary']['fmt'],
                           preempted_by=row['preempted-by-thread']['fmt'], core=row['core']['fmt'])
    calls = []
    for row in syscalls.query(start, end):
        length = overlap(start, end, number(row, 'start'), number(row, 'start')+number(row, 'duration'))
        if length:
            calls.append(dict(name=row['call']['fmt'], overlap_ns=length, duration_ns=number(row, 'duration'),
                              errno=row.get('errno', {}).get('fmt'), frames=row.get('backtrace', {}).get('frames')))
    vm = []
    for row in faults.query(start, end):
        length = overlap(start, end, number(row, 'start'), number(row, 'start')+number(row, 'duration'))
        if length:
            vm.append(dict(operation=row['operation']['fmt'], overlap_ns=length))
    return dict(state_seconds=dict(durations), covered_s=sum(durations.values()),
                unobserved_s=max(0, (end-start)*1e-9-sum(durations.values())),
                longest_state=longest, syscalls=calls, faults=vm)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--sessions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--existing-xml', type=Path)
    a = parser.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    xml = a.existing_xml or ROOT/'build/phase58_fix_frozen'/(out.name+'_xml')
    xml.mkdir(parents=True, exist_ok=True)
    sessions = []
    for path in a.sessions.rglob('summary.json'):
        s = json.loads(path.read_text())
        if 'dsp_thread' in s:
            sessions.append((path.parent, s))
    tids = {s['dsp_thread'] for _, s in sessions}
    exports = []
    for schema in SCHEMAS:
        path = xml/(schema+'.xml')
        if path.exists() and not complete_export(path):
            incomplete=path.with_name(path.name+'.incomplete_'+sha(path)[:12])
            if incomplete.exists():
                raise RuntimeError('Duplicate incomplete export; preserve and choose a fresh XML directory')
            path.rename(incomplete)
            (out/(schema+'_incomplete.json')).write_text(json.dumps(dict(path=str(incomplete),sha256=sha(incomplete),reason='Missing XML terminator; partial export retained'),indent=2)+'\n')
        if not path.exists():
            cmd = ['xcrun', 'xctrace', 'export', '--input', str(a.trace.resolve()), '--xpath',
                   '/trace-toc/run[@number="1"]/data/table[@schema="'+schema+'"]']
            with path.open('w') as f, (out/(schema+'_export.log')).open('w') as log:
                r = subprocess.run(cmd, stdout=f, stderr=log, timeout=180)
            if r.returncode or not complete_export(path):
                raise RuntimeError('Trace export failed: '+schema)
        exports.append(dict(schema=schema, path=str(path), sha256=sha(path), bytes=path.stat().st_size))
        print('export', schema, path.stat().st_size, flush=True)
    (out/'exports.json').write_text(json.dumps(exports, indent=2)+'\n')
    clock = table(xml/'time-info.xml')[0]
    timebase = clock['timebase-info']['fmt'].split('/')
    trace_epoch = number(clock, 'mabs-epoch')*int(timebase[0])/int(timebase[1])
    states = table(xml/'thread-state.xml', tids)
    calls = table(xml/'syscall.xml', tids)
    faults = table(xml/'virtual-memory.xml', tids)
    result = []
    payloads = []
    for folder, s in sessions:
        tid = s['dsp_thread']
        st = [r for r in states if r['thread']['tid']==tid]
        sc = [r for r in calls if r['thread']['tid']==tid]
        vm = [r for r in faults if r['thread']['tid']==tid]
        state_index, call_index, vm_index = IntervalIndex(st), IntervalIndex(sc), IntervalIndex(vm)
        callbacks = list(csv.DictReader((folder/'callbacks.csv').open()))
        first = next(r for r in callbacks if int(r['received']))
        origin = (s['clock_mach_ns']-s['clock_pipeline_s']*1e9 if 'clock_mach_ns' in s
                  else int(first['start_ns'])-s['first_callback_s']*1e9)
        pipeline_in_trace = origin-trace_epoch
        blocks = []
        for r in csv.DictReader((folder/'worker.csv').open()):
            start = pipeline_in_trace+float(r['start_s'])*1e9
            end = pipeline_in_trace+float(r['published_s'])*1e9
            item = dict(output_start=int(r['output_start']), output_end=int(r['output_end']),
                        start_s=float(r['start_s']), published_s=float(r['published_s']),
                        fifo_before=int(r['fifo_before']), wall_s=float(r['wall_s']), cpu_s=float(r['cpu_s']),
                        non_cpu_s=float(r['wall_s'])-float(r['cpu_s']),realtime=r.get('realtime')=='1')
            item['os'] = classify(start, end, state_index, call_index, vm_index)
            cb = [c for c in callbacks if start <= int(c['start_ns'])-trace_epoch < end]
            item['callbacks_in_block'] = len(cb)
            item['requested_in_block'] = sum(int(c['wanted']) for c in cb)
            item['received_in_block'] = sum(int(c['received']) for c in cb)
            item['missing_in_block'] = sum(int(c['wanted'])-int(c['received']) for c in cb)
            blocks.append(item)
        intervals, stack = [], []
        detail_path = folder/'detail.csv'
        if detail_path.exists():
            for r in csv.DictReader(detail_path.open()):
                key = (int(r['stage']), int(r['scope']))
                if int(r['begin']):
                    stack.append((key, r))
                    continue
                if not stack or stack[-1][0]!=key:
                    raise RuntimeError('Unbalanced detail trace: '+str(folder))
                _, begin = stack.pop()
                first_s, last_s = float(begin['at_s']), float(r['at_s'])
                cpu_s = float(r['cpu_s'])-float(begin['cpu_s'])
                item = dict(stage=key[0], scope=key[1], start_s=first_s, end_s=last_s,
                            wall_s=last_s-first_s, cpu_s=cpu_s, non_cpu_s=last_s-first_s-cpu_s,
                            cpp_new_calls=int(r['cpp_new_calls'])-int(begin['cpp_new_calls']),
                            realtime=any(b['realtime'] and b['start_s']<=first_s and last_s<=b['published_s'] for b in blocks))
                item['os'] = classify(pipeline_in_trace+first_s*1e9, pipeline_in_trace+last_s*1e9, state_index, call_index, vm_index)
                intervals.append(item)
            if stack and not s.get('detail_dropped'):
                raise RuntimeError('Unclosed detail trace: '+str(folder))
        target = out/folder.name
        target.mkdir()
        for name, data in (('dsp_thread_states', st), ('dsp_syscalls', sc), ('dsp_vm', vm),
                           ('blocks', blocks), ('stages', intervals)):
            encoded=(json.dumps(data, indent=2)+'\n').encode()
            path=target/(name+'.json')
            if len(encoded)>1024*1024:
                path=path.with_suffix('.json.gz')
                with gzip.open(path,'wb',compresslevel=1) as f:f.write(encoded)
            else:path.write_bytes(encoded)
            payloads.append(dict(path=str(path),uncompressed_bytes=len(encoded),uncompressed_sha256=hashlib.sha256(encoded).hexdigest()))
        row = dict(session=str(folder), thread=tid, PASS=s['PASS'], missing_frames=s['missing_frames'],
                   bridge_uncertainty_s=s['bridge_uncertainty_s'], pipeline_start_in_trace_s=pipeline_in_trace*1e-9,
                   state_rows=len(st), syscall_rows=len(sc), fault_rows=len(vm),
                   worst_blocks=sorted(blocks, key=lambda r:r['non_cpu_s'], reverse=True)[:3],
                   realtime_blocks=sum(b['realtime'] for b in blocks),
                   worst_realtime_blocks=sorted((b for b in blocks if b['realtime']),key=lambda r:r['non_cpu_s'],reverse=True)[:3],
                   worst_realtime_phase_intervals=sorted((r for r in intervals if r['stage']==2 and r['realtime']),key=lambda r:r['non_cpu_s'],reverse=True)[:3],
                   worst_phase_intervals=sorted((r for r in intervals if r['stage']==2), key=lambda r:r['non_cpu_s'], reverse=True)[:3])
        result.append(row)
        print(folder.name, 'missing', s['missing_frames'], 'states', len(st), flush=True)
    (out/'summary.json').write_text(json.dumps(dict(trace_epoch_ns=trace_epoch, sessions=result), indent=2)+'\n')
    (out/'payloads.json').write_text(json.dumps(payloads,indent=2)+'\n')


if __name__ == '__main__':
    main()
