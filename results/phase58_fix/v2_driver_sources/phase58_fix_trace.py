"""Trace fresh pipeline sessions in one targeted process; preserve failures."""
import argparse
import datetime
import json
import subprocess
from pathlib import Path
from phase58_fix_repeat import sha

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=20)
    p.add_argument('--window-s', type=int, default=30)
    p.add_argument('--extra', action='append', default=None)
    a = p.parse_args()
    a.extra = a.extra or ['--profile=detail']
    if not 1 <= a.repeats <= 100 or not 5 <= a.window_s <= 300:
        p.error('focused trace sessions must be 1..100')
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = ROOT/'results/phase58/native_product/inputs/boundary_1_2_48000.wav'
    oracle = ROOT/'build/phase58_frozen/product_reference'
    raw = out/'reference.f32'
    r = subprocess.run(list(map(str, [oracle, source, 2000000, 'candidate', raw])), capture_output=True, text=True)
    (out/'reference.log').write_text(r.stdout+r.stderr)
    if r.returncode:
        raise RuntimeError('Independent reference failed')
    ref = json.loads(r.stdout)
    (out/'reference.json').write_text(json.dumps(ref, indent=2)+'\n')
    binary = a.binary.resolve()
    trace = ROOT/'build/phase58_fix_frozen'/(out.name+'.trace')
    native = list(map(str, [binary, source, 2000000, 'candidate', raw, ref['output_frames'], ref['pcm_sha256'],
                            out/'sessions', 'repeat', 0, 0, 0, 0, 0, '--sessions='+str(a.repeats), *a.extra]))
    cmd = ['xcrun', 'xctrace', 'record', '--template', 'Audio System Trace', '--output', str(trace),
           '--time-limit', '300s', '--window', str(a.window_s)+'s', '--no-prompt', '--target-stdout', str(out/'native_stdout.txt'),
           '--launch', '--', *native]
    manifest = dict(start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    input=str(source), input_sha256=sha(source), binary=str(binary), binary_sha256=sha(binary),
                    reference_binary_sha256=sha(oracle), head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    scope='Independent pipeline sessions in one process; diagnostic trace overhead included',
                    fix_workgroup_requested='--worker=workgroup' in a.extra, requested_sessions=a.repeats, command=cmd)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    with (out/'record.log').open('w') as log:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=420)
    rows = []
    for path in sorted((out/'sessions').glob('session_*/summary.json')):
        rows.append(dict(path=str(path.relative_to(out)), summary=json.loads(path.read_text())))
    result = dict(trace_exit=r.returncode, trace_path=str(trace), sessions=len(rows), requested=a.repeats,
                  passed=sum(bool(x['summary']['PASS']) for x in rows),
                  failed=sum(not x['summary']['PASS'] for x in rows),
                  end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), rows=rows)
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print({k:v for k,v in result.items() if k!='rows'}, flush=True)
    return 0 if r.returncode==0 and len(rows)==a.repeats and result['failed']==0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
