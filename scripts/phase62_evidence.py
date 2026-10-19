"""期待台帳を先に固定し、欠落・途中終了・実時間異常を残す検証記録。"""
import hashlib
import json
import math
import subprocess
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

GATES = ('functional', 'raw', 'boundary_time', 'realtime', 'quality', 'public')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path):
    path = Path(path).resolve()
    return dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path))


def verify_architecture(paths, architecture='arm64'):
    """固定oracleと同じCPU命令形式を要求。Rosettaによる既定選択に依存しない。"""
    rows=[]
    for path in paths:
        process=subprocess.run(['/usr/bin/lipo','-archs',str(path)],capture_output=True,text=True)
        arches=process.stdout.split()
        rows.append(dict(path=str(path),architectures=arches,exit=process.returncode,
                         PASS=process.returncode==0 and arches==[architecture]))
    return dict(PASS=bool(rows) and all(row['PASS'] for row in rows),expected=architecture,files=rows)


def guard_device_buffer(command, report):
    """子試験の異常終了時にも、親プロセスから元の装置バッファへ戻す。"""
    import ctypes
    import signal
    class Address(ctypes.Structure):
        _fields_=[('selector',ctypes.c_uint32),('scope',ctypes.c_uint32),('element',ctypes.c_uint32)]
    four=lambda value:int.from_bytes(value.encode(),'big')
    audio=ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
    def get(obj,selector):
        address=Address(four(selector),four('glob'),0);value=ctypes.c_uint32();size=ctypes.c_uint32(ctypes.sizeof(value))
        code=audio.AudioObjectGetPropertyData(obj,ctypes.byref(address),0,None,ctypes.byref(size),ctypes.byref(value))
        if code:raise RuntimeError('CoreAudio get '+selector+': '+str(code))
        return value.value
    device=get(1,'dOut');original=get(device,'fsiz');result=dict(device=device,original=original,command=list(map(str,command)),restored=False)
    child=None
    def interrupted(signum,frame):raise KeyboardInterrupt('signal '+str(signum))
    previous=signal.signal(signal.SIGTERM,interrupted)
    try:
        child=subprocess.Popen(result['command']);result['child_exit']=child.wait(timeout=1200)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        try:
            result['after_child']=get(device,'fsiz')
            if result['after_child']!=original:
                address=Address(four('fsiz'),four('glob'),0);value=ctypes.c_uint32(original)
                status=audio.AudioObjectSetPropertyData(device,ctypes.byref(address),0,None,ctypes.sizeof(value),ctypes.byref(value))
                if status:raise RuntimeError('CoreAudio buffer restore: '+str(status))
            deadline=time.monotonic()+5
            while get(device,'fsiz')!=original:
                if time.monotonic()>deadline:raise TimeoutError('buffer restore confirmation')
                time.sleep(.01)
            result['restored']=True;result['default_device_after']=get(1,'dOut')
        except Exception as error:result['restore_error']=str(error)
        signal.signal(signal.SIGTERM,previous)
        result['PASS']=result.get('child_exit')==0 and result['restored'] and result.get('default_device_after')==device
        Path(report).write_text(json.dumps(result,indent=2)+'\n')
    return 0 if result['PASS'] else 1


def source_manifest(root):
    root = Path(root)
    paths = [root/'CMakeLists.txt']
    for directory in ('src', 'tests', 'scripts'):
        paths.extend(p for p in (root/directory).rglob('*') if p.is_file() and
                     p.suffix in ('.h', '.hpp', '.cpp', '.mm', '.py', '.c', '.m'))
    rows = [dict(path=str(p.relative_to(root)), sha256=sha(p)) for p in sorted(paths)]
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return dict(sha256=digest, files=rows)


def bit_exact_finite(actual, expected):
    """float32の数値等値ではなく全ビットを比較。NaN/Infは別に拒否。"""
    import struct
    if len(actual) != len(expected) or len(actual) % 4:
        return False
    finite = all(math.isfinite(x[0]) for data in (actual, expected)
                 for x in struct.iter_unpack('<f', data))
    return finite and actual == expected


def inspect_case(spec, root, exit_code):
    gates = {gate: None for gate in GATES}
    reasons = []
    missing = [name for name in spec.get('required', []) if not (root/name).is_file()]
    if missing:
        return gates, ['必須生成物が欠落: '+', '.join(missing)]
    kind = spec.get('kind', 'exit')
    gates['functional'] = exit_code == 0
    try:
        if kind == 'ctest':
            xml = ET.parse(root/spec['result']).getroot()
            cases = xml.findall('.//testcase')
            names = [case.get('name') for case in cases]
            expected = spec.get('test_names')
            if expected is None:
                expected = json.loads((root/spec['test_names_file']).read_text())
            gates['functional'] = (exit_code == 0 and bool(cases) and
                sorted(names) == sorted(expected) and
                not any(case.find(tag) is not None for case in cases
                        for tag in ('failure', 'error', 'skipped')))
            if not gates['functional']:
                reasons.append('CTest実結果の件数・名前・完了・成功が期待台帳と一致しない')
        elif kind in ('exact', 'golden'):
            value = json.loads((root/spec['result']).read_text())
            folder=(root/spec['result']).parent
            if kind=='exact':
                rows=[json.loads(line) for line in (folder/'rows.jsonl').read_text().splitlines()]
                count=sum(bool(row['exit']==0 and row['result'] and row['result']['PASS'] is True) for row in rows)
                unique={(row['name'],row['input_frame'],row['mode']) for row in rows}
            else:
                rows=value['results'];count=sum(row['exit']==0 and row['PASS'] is True for row in rows)
                unique={(row['name'],row['speed']) for row in rows}
            failed=len(rows)-count
            gates['raw'] = (count == spec['expected_count'] and not failed and
                            len(unique)==len(rows)==spec['expected_count'] and value['passed']==count and
                            value.get('PASS', True) is True)
            gates['functional'] &= gates['raw']
        elif kind=='checks':
            from collections import Counter
            rows=[json.loads(line) for line in (root/spec['result']).read_text().splitlines()]
            gates['functional'] &= bool(rows) and Counter(row['check'] for row in rows)==Counter(spec['checks']) and all(row['PASS'] is True for row in rows)
        elif kind == 'native':
            value = json.loads((root/spec['result']).read_text())
            expected = ('functional_pass', 'raw_mix_errors', 'nonfinite',
                        'safety_stop_frames', 'missing_frames', 'underrun_calls',
                        'callback_deadlines', 'host_errors', 'sample_errors',
                        'hal_window_misses', 'callback_new', 'callback_heap_calls',
                        'callback_frees', 'final_worker_deadlines',
                        'final_workgroup_errors', 'final_missing_frames', 'final_worker_new', 'cycles')
            absent = [key for key in expected if key not in value]
            if absent:
                return gates, ['実機の必須診断フィールド欠落: '+', '.join(absent)]
            gates['functional'] &= value['functional_pass'] is True and value['cycles'] >= spec['cycles']
            gates['raw'] = not (value['raw_mix_errors'] or value['nonfinite'])
            gates['boundary_time'] = gates['raw'] and not value['safety_stop_frames']
            boundary_file=root/Path(spec['result']).parent/'boundaries.jsonl'
            events=[json.loads(line) for line in boundary_file.read_text().splitlines()]
            checked=0
            for prior,current in zip(events,events[1:]):
                if prior['new_epoch']!=current['old_epoch']:continue
                checked+=1
                expected_length=current['old_output_end']-prior['new_output_start']
                if not spec.get('period_preserving'):expected_length-=current['overlap']
                if current['callback_frame']-prior['callback_frame']!=expected_length:gates['boundary_time']=False
            if spec.get('period_preserving'):
                required=('failure_padding_frames','output_affected_frames','period_frames','map_builds','workers_created')
                if any(key not in value for key in required):return gates,['新周期契約の診断が欠落']
                gates['boundary_time'] &= bool(checked) and all(not event['overlap'] for event in events) and value['period_frames']>=512
                gates['functional'] &= value['map_builds']==1 and value['workers_created']==2
                gates['realtime']=not (value['failure_padding_frames'] or value['output_affected_frames'])

            gates['realtime'] = gates['realtime'] is not False and not any(value[key] for key in (
                'safety_stop_frames', 'missing_frames', 'underrun_calls',
                'callback_deadlines', 'host_errors', 'sample_errors',
                'hal_window_misses', 'callback_new', 'callback_heap_calls',
                'callback_frees', 'final_worker_deadlines', 'final_worker_new', 'final_missing_frames', 'final_workgroup_errors'))
            if spec.get('clear_contract'):
                gates['realtime'] &= not any(value[key] for key in ('invalid_sample_time_calls','invalid_rate_scalar_calls'))
                clear=json.loads((root/Path(spec['result']).parent/'clear_result.json').read_text())
                gates['functional'] &= clear['PASS'] is True and clear['connection_counted_as_cycle'] is False
                gates['boundary_time'] &= clear['connection_counted_as_cycle'] is False
                gates['realtime'] &= not any(clear[key] for key in ('failure_padding_frames','output_affected_frames','missing_frames','callback_deadlines','host_errors','sample_errors','hal_window_misses'))
        elif kind == 'period_capture':
            value=json.loads((root/spec['result']).read_text())
            gates['functional'] &= value['PASS'] is True and value['cycles']>0
            gates['raw'] = value['raw_bit_errors']==0
            gates['boundary_time'] = value['period_frames']>=512 and value['output_frames']==value['cycles']*value['period_frames']
        elif kind in ('json_pass','quality'):
            value = json.loads((root/spec['result']).read_text())
            gates['functional'] &= value['PASS'] is True
            if kind=='quality':
                gates['raw']=value['bit_exact'] is True and value['finite'] is True
                gates['quality']=gates['functional'] and gates['raw']
        elif kind == 'pcm':
            gates['raw'] = exit_code == 0
        elif kind != 'exit':
            return gates, ['未知の検証種別: '+kind]
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as error:
        return gates, ['結果を検査不能: '+str(error)]
    return gates, reasons


def gate_verdicts(cases, rows):
    expected_by_kind={'native':('functional','raw','boundary_time','realtime'),
                      'pcm':('functional','raw'),'period_capture':('functional','raw','boundary_time'),
                      'exact':('functional','raw'),'golden':('functional','raw'),
                      'quality':('functional','raw','quality')}
    gates={};coverage={}
    for gate in GATES:
        expected=[case['id'] for case in cases if gate in case.get('gates',expected_by_kind.get(case.get('kind'),('functional',)))]
        selected=[rows[name] for name in expected]
        coverage[gate]=dict(expected=len(selected),measured=sum(row['gates'][gate] is not None for row in selected))
        values=[row['gates'][gate] for row in selected]
        gates[gate]=False if any(value is False for value in values) else True if selected and all(row['status']=='PASS' and row['gates'][gate] is True for row in selected) else None
    return gates,coverage


class Ledger:
    def __init__(self, root, cases, provenance):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        ids = [case['id'] for case in cases]
        if not cases or len(set(ids)) != len(ids):
            raise ValueError('期待ケースは非空でID重複不可')
        self.plan = dict(schema=1, provenance=provenance, cases=cases)
        (self.root/'EXPECTED.json').write_text(json.dumps(self.plan, ensure_ascii=False, indent=2)+'\n')
        self.rows = {case['id']:dict(id=case['id'], status='NOT_RUN', gates={gate: None for gate in GATES}) for case in cases}
        self.save()

    def save(self):
        statuses = ('PASS', 'FAIL', 'NOT_RUN', 'INCOMPLETE')
        counts = {state:sum(row['status'] == state for row in self.rows.values()) for state in statuses}
        gates,coverage=gate_verdicts(self.plan['cases'],self.rows)
        complete = not (counts['NOT_RUN'] or counts['INCOMPLETE'])
        result = dict(schema=1, expected=len(self.rows), counts=counts,
                      PASS=complete and not counts['FAIL'] and counts['PASS'] > 0,
                      gates=gates, gate_coverage=coverage, cases=list(self.rows.values()))
        (self.root/'LEDGER.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        return result

    def run(self, case_id, command, *, cwd, timeout=1800, inputs=()):
        spec = next(case for case in self.plan['cases'] if case['id'] == case_id)
        row = self.rows[case_id]
        if row['status'] != 'NOT_RUN':
            raise ValueError('同一ケースの再実行は別の新規台帳へ記録してください')
        # 既存生成物の再採用を禁止。失敗ログも上書きしない。
        existing = [p for p in spec.get('required', []) if (self.root/p).exists()]
        if existing:
            row.update(status='INCOMPLETE', reasons=['実行前に生成物が存在: '+', '.join(existing)])
            self.save()
            return False
        row.update(command=list(map(str, command)), status='INCOMPLETE', started_ns=time.time_ns(),
                   inputs=[identity(p) for p in inputs])
        executable = Path(shutil.which(str(command[0])) or str(command[0]))
        if executable.is_file():
            row['executable'] = identity(executable)
        self.save()
        start = time.monotonic()
        try:
            with (self.root/(case_id+'.log')).open('x') as log:
                completed = subprocess.run(row['command'], cwd=cwd, stdout=log,
                                           stderr=subprocess.STDOUT, timeout=timeout)
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code = -1
            row['timeout'] = True
        except OSError as error:
            code = -2
            row['launch_error'] = str(error)
        gates, reasons = inspect_case(spec, self.root, code)
        row.update(exit=code, wall_s=time.monotonic()-start, gates=gates, reasons=reasons,
                   artifacts=[identity(self.root/p) for p in spec.get('required', []) if (self.root/p).is_file()])
        row['status'] = 'FAIL' if code or any(v is False for v in gates.values()) else 'INCOMPLETE' if reasons else 'PASS'
        self.save()
        return row['status'] == 'PASS'


def aggregate(root):
    root = Path(root)
    if not (root/'EXPECTED.json').is_file() or not (root/'LEDGER.json').is_file():
        return dict(PASS=False, status='INCOMPLETE', reason='実行前の期待台帳または実結果台帳がない', public_go=False)
    plan = json.loads((root/'EXPECTED.json').read_text())
    data = json.loads((root/'LEDGER.json').read_text())
    expected = {case['id'] for case in plan['cases']}
    actual = {case['id'] for case in data['cases']}
    valid = bool(expected) and expected == actual and len(data['cases']) == len(expected)
    specs={case['id']:case for case in plan['cases']}
    for row in data['cases']:
        if row.get('exit') is not None and row['status'] not in ('NOT_RUN','INCOMPLETE'):
            gates,reasons=inspect_case(specs[row['id']],root,row['exit'])
            row['gates']=gates
            row['status']='FAIL' if row['exit'] or any(v is False for v in gates.values()) else 'INCOMPLETE' if reasons else 'PASS'
        for artifact in row.get('artifacts', []):
            path = Path(artifact['path'])
            if not path.is_file() or sha(path) != artifact['sha256']:
                row['status'] = 'INCOMPLETE'
                valid = False
    data['counts'] = {state:sum(row['status'] == state for row in data['cases']) for state in ('PASS', 'FAIL', 'NOT_RUN', 'INCOMPLETE')}
    data['PASS'] = valid and all(row['status'] == 'PASS' for row in data['cases'])
    data['gates'],data['gate_coverage']=gate_verdicts(plan['cases'],{row['id']:row for row in data['cases']})
    data['public_go'] = False
    return data


if __name__=='__main__':
    import argparse
    import sys
    if sys.argv[1:2]==['--guard-device-buffer']:
        raise SystemExit(guard_device_buffer(sys.argv[3:],Path(sys.argv[2])))
    parser=argparse.ArgumentParser();parser.add_argument('--architecture',default='arm64');parser.add_argument('paths',nargs='+',type=Path);args=parser.parse_args()
    result=verify_architecture(args.paths,args.architecture);print(json.dumps(result,indent=2));raise SystemExit(int(not result['PASS']))
