#!/usr/bin/env python3
"""Run Phase 5.2 A/B/C on one identical section of each supplied source."""
import argparse
import concurrent.futures
import csv
import pathlib
import subprocess


def run(command):
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    for name in ('bass', 'mix', 'female', 'male'):
        parser.add_argument(name, type=pathlib.Path)
    parser.add_argument('--start', type=float, default=90)
    parser.add_argument('--duration', type=float, default=45)
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parent.parent
    result = root / 'results/phase52/real'
    result.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for name in ('bass', 'mix', 'female', 'male'):
        source = getattr(args, name)
        if not source.is_file():
            raise FileNotFoundError(source)
        target = result / f'{name}_input.wav'
        run(['ffmpeg', '-v', 'error', '-y', '-ss', str(args.start), '-i', str(source),
             '-t', str(args.duration), '-c:a', 'pcm_f32le', str(target)])
        inputs[name] = target
    commands = []
    for name, source in inputs.items():
        for speed in ('0.75', '0.50'):
            for mode in 'abc':
                target = result / f'{name}_{speed.replace(".", "")}_{mode}.wav'
                commands.append((name, speed, mode, source, target))

    def process(job):
        name, speed, mode, source, target = job
        line = run([str(root / 'build/timestretch'), str(source), str(target),
                    '--speed', speed, '--phase-locking', 'on', '--transient', 'on',
                    '--adaptive-time-map', 'on', '--precise-anchoring', 'on',
                    '--stereo-coherence', 'on', '--multiresolution', 'on',
                    '--chunked', 'on', '--ablation', mode])
        print(f'{name} {speed} {mode}: {line}', flush=True)
        fields = dict(part.split('=', 1) for part in line.split() if '=' in part)
        return {'name': name, 'speed': speed, 'mode': mode,
                'input': str(source), 'output': str(target), **fields}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(process, commands))
    with (result / 'manifest.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    by_input_speed = {}
    for record in records:
        by_input_speed.setdefault((record['name'], record['speed']), []).append(record)
    for key, group in by_input_speed.items():
        if len({r['time_map_hash'] for r in group}) != 1 or \
           len({r['output_frames'] for r in group}) != 1 or \
           len({r['event_count'] for r in group}) != 1:
            raise AssertionError(f'A/B/C timeline mismatch: {key}')
    print('All A/B/C input sections, time maps, events, and output lengths match.', flush=True)


if __name__ == '__main__':
    main()
