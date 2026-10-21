"""F01の影響を受ける既存75 program/326 checksを新binaryで直列実行する。"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--build-provenance', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build, provenance, out = [x.resolve() for x in (args.build, args.build_provenance, args.output)]
    out.mkdir(parents=True, exist_ok=False)
    assert out.is_relative_to(ROOT / 'build')
    source = source_manifest(ROOT)
    assert json.loads(provenance.read_text())['source_inventory_sha256'] == source['sha256']
    src = ROOT / 'results/phase31/input/mix.wav'
    other = ROOT / 'build/phase62/run_01/step1_release/mix_repeat_36s.wav'
    inputs = ROOT / 'build/phase62_e5_review_20261021_01/inputs'
    jobs = []
    for suite, programs, checks in [('adoption', 12, 78), ('fault', 10, 70), ('partial', 6, 6)]:
        jobs.append(dict(id=suite, programs=programs, checks=checks, command=list(map(str, [
            sys.executable, '-B', ROOT / 'scripts/phase62_review_validation.py',
            '--suite', suite, '--build', build, '--inputs', inputs,
            '--output', out / suite, '--build-provenance', provenance]))))
    for suite, programs, checks in [('control', 5, 42), ('playing', 12, 74), ('api', 16, 16), ('paused-clear', 12, 24)]:
        command = [sys.executable, '-B', ROOT / ('scripts/phase62_finish_control_validation.py' if suite == 'control' else 'scripts/phase62_finish_validation.py')]
        if suite != 'control':
            command += ['--suite', suite, '--build-provenance', provenance]
        command += ['--build', build, '--input', src, '--output', out / suite]
        if suite == 'playing':
            command += ['--other-input', other]
        jobs.append(dict(id=suite, programs=programs, checks=checks, command=list(map(str, command))))
    for preset in ['candidate', 'baseline']:
        key = 'race_' + preset
        jobs.append(dict(id=key, programs=1, checks=8, command=list(map(str, [build / 'phase62_race_native', src, preset, out / key, other]))))
    assert sum(j['programs'] for j in jobs) == 75 and sum(j['checks'] for j in jobs) == 326
    save(out / 'EXPECTED.json', dict(source=source, build_provenance=identity(provenance),
         driver=identity(Path(__file__)), interpreter=identity(Path(sys.executable)),
         inputs=[identity(p) for p in sorted(inputs.glob('*.wav'))] + [identity(src), identity(other)],
         jobs=jobs, required_ids=[j['id'] for j in jobs], expected_programs=75,
         expected_checks=326, serial_audio=True, RT_deadline_approval='NOT_ASSESSED'))
    rows = []
    for job in jobs:
        assert source_manifest(ROOT) == source
        log = out / (job['id'] + '.log')
        began = time.monotonic()
        timed = False
        with log.open('w') as stream:
            child = subprocess.Popen(job['command'], stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = child.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                timed = True
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                code = None
        path = out / job['id'] / 'SUMMARY.json'
        result = json.loads(path.read_text()) if path.exists() else {}
        if job['id'].startswith('race_'):
            complete = result.get('expected') == result.get('executed') == result.get('PASS') == job['checks']
            programs, checks = (1 if complete else 0), result.get('executed', 0)
        else:
            programs, checks = result.get('executed_programs', 0), result.get('executed_checks', 0)
            complete = (result.get('run_complete') is True and result.get('status') == 'PASS'
                        and result.get('expected_programs') == programs == job['programs']
                        and result.get('expected_checks') == checks == job['checks'])
        ok = complete and code == 0 and not timed and source_manifest(ROOT) == source
        status = 'PASS' if ok else 'INCOMPLETE' if timed else 'FAIL'
        rows.append(dict(id=job['id'], status=status, exit=code, timed_out=timed,
                         programs=programs, checks=checks, seconds=time.monotonic()-began,
                         result=result, summary=identity(path) if path.exists() else None, log=identity(log)))
        done = len(rows) == len(jobs)
        save(out / 'SUMMARY.json', dict(status='PASS' if done and all(r['status'] == 'PASS' for r in rows) else 'INCOMPLETE',
             run_complete=done, source_inventory_sha256=source['sha256'], required_ids=[j['id'] for j in jobs],
             expected_programs=75, executed_programs=sum(r['programs'] for r in rows),
             expected_checks=326, executed_checks=sum(r['checks'] for r in rows), rows=rows,
             local_overall_go=False))
        print(job['id'], status, programs, checks, round(rows[-1]['seconds'], 2), flush=True)
        if not ok:
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
