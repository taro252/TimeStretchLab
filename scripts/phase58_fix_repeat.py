"""Run independent native sessions serially and retain every result."""
import argparse
import csv
import datetime
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--binary', type=Path, default=ROOT/'build/phase58_native')
    p.add_argument('--input', type=Path, default=ROOT/'results/phase58/native_product/inputs/boundary_1_2_48000.wav')
    p.add_argument('--repeats', type=int, default=20)
    p.add_argument('--speed', type=int, default=2000000)
    p.add_argument('--preset', choices=('candidate', 'baseline'), default='candidate')
    p.add_argument('--cpu', type=int, default=0)
    p.add_argument('--memory', type=int, default=0)
    p.add_argument('--extra', action='append', default=[])
    p.add_argument('--expected-device', type=int, default=72)
    p.add_argument('--expected-device-rate', type=int, default=48000)
    p.add_argument('--expected-buffer', type=int, default=512)
    a = p.parse_args()
    if not 1 <= a.repeats <= 1000:
        p.error('repeats must be 1..1000')
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    binary, source = a.binary.resolve(), a.input.resolve()
    worker_mode=next((x.split('=',1)[1] for x in reversed(a.extra) if x.startswith('--worker=')), 'standard')
    resident=next((x.split('=',1)[1] for x in reversed(a.extra) if x.startswith('--resident-input=')), 'off')=='on'
    reference = ROOT/'build/phase58_frozen/product_reference'
    raw = out/'reference.f32'
    r = subprocess.run([str(reference), str(source), str(a.speed), a.preset, str(raw)], capture_output=True, text=True)
    (out/'reference.log').write_text(r.stdout+r.stderr)
    if r.returncode:
        raise RuntimeError('Independent reference failed')
    ref = json.loads(r.stdout)
    (out/'reference.json').write_text(json.dumps(ref, indent=2)+'\n')
    manifest = dict(start_utc=utc(), head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    input=str(source), input_sha256=sha(source), binary=str(binary), binary_sha256=sha(binary),
                    reference_binary_sha256=sha(reference), preset=a.preset, speed_micros=a.speed,
                    analysis_chunk=32768, fifo_capacity=16384, lead=16384 if a.preset=='candidate' else 12288,
                    block=2048, gain=0.5, cpu_load_threads=a.cpu, memory_load_mib=a.memory, extra=a.extra,
                    os_environment=str(ROOT/'results/phase58_fix/START_STATE.json'), qos_actual_measured=None,
                    requested_initial_dsp_qos='USER_INITIATED', requested_analysis_qos='UTILITY',
                    worker_mode=worker_mode,resident_input=resident,system_load_measured=False,
                    expected_device=a.expected_device,expected_device_rate=a.expected_device_rate,expected_buffer=a.expected_buffer,
                    driver_source_sha256=sha(Path(__file__)))
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    rows = []
    for i in range(a.repeats):
        cmd = list(map(str, [binary, source, a.speed, a.preset, raw, ref['output_frames'], ref['pcm_sha256'],
                            out/f'run_{i:03}', 'normal', 0, a.cpu, a.memory, 0, 0, *a.extra]))
        row = dict(index=i, start_utc=utc(), command=cmd)
        started = time.monotonic()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            row.update(exit=r.returncode, stdout=r.stdout, stderr=r.stderr)
        except subprocess.TimeoutExpired as e:
            row.update(exit=None, timeout=True, stdout=str(e.stdout), stderr=str(e.stderr))
        row.update(end_utc=utc(), elapsed_s=time.monotonic()-started)
        (out/f'run_{i:03}.log').write_text(row['stdout']+row['stderr'])
        summary = out/f'run_{i:03}/summary.json'
        if summary.exists():
            row['summary'] = json.loads(summary.read_text())
            s=row['summary']
            row['conditions_valid']=(s['device_id']==a.expected_device and s['device_rate']==a.expected_device_rate
                and s['device_buffer_frames']==a.expected_buffer and s['speed_micros']==a.speed and s['preset']==a.preset
                and bool(s.get('workgroup_enabled',False))==(worker_mode=='workgroup')
                and bool(s.get('resident_input_bytes',0))==resident)
            worker_csv=out/f'run_{i:03}/worker.csv'
            blocks=list(csv.DictReader(worker_csv.open())) if worker_csv.exists() else []
            rt_blocks=[b for b in blocks if b.get('realtime')=='1']
            row['block_statistics']={}
            for label,data in (('all',blocks),('realtime',rt_blocks)):
                row['block_statistics'][label]=dict(n=len(data),max_wall_s=max((float(b['wall_s']) for b in data),default=None),
                    max_cpu_s=max((float(b['cpu_s']) for b in data),default=None),
                    max_non_cpu_s=max((float(b['wall_s'])-float(b['cpu_s']) for b in data),default=None))
        row['PASS']=(row['exit']==0 and row.get('summary',{}).get('PASS',False)
                     and row.get('summary',{}).get('pcm_complete_exact',False) and row.get('conditions_valid',False))
        rows.append(row)
        with (out/'rows.jsonl').open('a') as f:
            f.write(json.dumps(row)+'\n')
        summary = dict(executions=len(rows), requested=a.repeats,
                       passed=sum(x['PASS'] for x in rows),failed=sum(not x['PASS'] for x in rows),
                       input_unchanged=sha(source)==manifest['input_sha256'],
                       binary_unchanged=sha(binary)==manifest['binary_sha256'])
        (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
        s = row.get('summary', {})
        print(i, row['exit'], 'missing', s.get('missing_frames'), 'max_wall', s.get('max_dsp_wall_s'),
              'max_cpu', s.get('max_dsp_cpu_s'), flush=True)
    manifest['end_utc'] = utc()
    manifest['qos_actual_measured']=all(r.get('summary',{}).get('dsp_qos_queried',False) for r in rows)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(summary), flush=True)
    return 0 if summary['failed']==0 and summary['input_unchanged'] and summary['binary_unchanged'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
