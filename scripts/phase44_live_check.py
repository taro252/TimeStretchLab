#!/usr/bin/env python3
"""Independent macOS device checks with immutable runs and a cumulative summary."""
import argparse
import os
import subprocess
from pathlib import Path
from phase45_store import new_run, parse_log, save_result
from phase45_verdict import live_failures

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=('mix', 'drums', 'vocal', 'guitar', 'bass'), default='mix')
    parser.add_argument('--minutes', default='3,5,10')
    parser.add_argument('--stress', action='store_true')
    parser.add_argument('--audible', action='store_true')
    parser.add_argument('--initial', default='0.4')
    parser.add_argument('--schedule', type=Path, default=ROOT / 'results/phase43/smoke_schedule.csv')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/phase45/live')
    args = parser.parse_args()
    failed = False
    for _ in range(args.repeat):
        for minutes in (int(item) for item in args.minutes.split(',')):
            if args.input:
                source = args.input
            elif args.source == 'mix':
                source = ROOT / 'results/phase14/benchmark' / f'mix_repeat_{minutes*60}.wav'
            elif args.source == 'drums':
                source = ROOT / 'results/phase40/long_input' / f'drums_repeat_{minutes*60}.wav'
            else:
                source = ROOT / f'results/phase31/input/{args.source}.wav'
            tag = f'{args.source}_manual_input' if args.input else f'{args.source}_{minutes}m'
            path, identifier, at = new_run(args.output, tag)
            environment = os.environ.copy()
            environment.pop('PHASE43_STRESS', None)
            if args.audible: environment.pop('PHASE43_SILENT', None)
            else: environment['PHASE43_SILENT'] = '1'
            if args.stress: environment['PHASE43_STRESS'] = '1'
            environment['PHASE45_LIVE_EVENTS'] = str(path / 'callbacks.csv')
            environment['PHASE45_LIVE_PLAN_CSV'] = str(path / 'replay.csv')
            command = [ROOT / 'build/phase43_play', source, args.initial, args.schedule]
            try:
                result = subprocess.run(list(map(str, command)), cwd=ROOT,
                    capture_output=True, text=True, env=environment, timeout=minutes*240+180)
                text = result.stdout + result.stderr
                code = result.returncode
            except subprocess.TimeoutExpired as error:
                text = (error.stdout or b'').decode() if isinstance(error.stdout, bytes) else error.stdout or ''
                text += '\nvalidation_timeout=1\n'
                code = 124
            (path / 'playback.log').write_text(text)
            values = parse_log(text)
            problems = live_failures(values, code)
            row = dict(run_id=identifier, run_time=at, source=args.source,
                input_path=str(source), input_minutes=minutes, stress=int(args.stress),
                audible=int(args.audible), initial_speed=args.initial, schedule=str(args.schedule),
                exit_code=code, quality='FAIL' if problems else 'PASS', failures=';'.join(problems))
            row.update(values)
            row.update(exit_code=code, quality='FAIL' if problems else 'PASS', failures=';'.join(problems))
            if 'input_frames' in values and 'dsp_sample_rate' in values:
                try:
                    row['requested_duration_label'] = minutes
                    row['input_minutes'] = int(values['input_frames'])/float(values['dsp_sample_rate'])/60
                except (ValueError, ZeroDivisionError): row['measured_input_minutes'] = 'invalid'
            save_result(args.output, path, row)
            failed |= bool(problems)
            print(identifier, row['quality'], row['failures'], flush=True)
    if failed: raise SystemExit('Mac callback validation FAIL; cumulative summary retained')


if __name__ == '__main__': main()
