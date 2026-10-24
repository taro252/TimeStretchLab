"""凍結Exact実行体でAB参照を生成。6素材/速度のRAW共有・12範囲Map、既存mono1x再利用。

製品DSPはlinkしない。入力/参照binary/log/RAW/Map/source manifestのSHAを保存する。
各oracle実行の4 queryを、独立に得たA30/B30/A270/B270の2組へ切り分ける。
"""
import argparse
import math
from pathlib import Path
import struct
import subprocess
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
ORACLE_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
MONO_RAW_SHA = '31e29e3c968672f821fe8887a702012810316687b192f6db4f1f670ffee381d2'
OLD_PINS = {'EXPECTED.json': '9f43a880c6ba5304a9f4617c54fbf0feb446f0840fd07f45508773ce152f6f47',
            'reference.log': '52ac58c6d90400daf363c37fd05bb3a0cb093f41c747f927eeb56ae361e671a5',
            'A30_fresh_map.json': '7bbedfaf03a7db58d57034817667f818227c9075d6c5705b1a8d465e8ad3b221',
            'A270_fresh_map.json': 'd22c0bdf461b7c59a5fc6cbf8e0a6221abda931008933a3b3747054b74cec579'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mono-input', type=Path, required=True)
    p.add_argument('--stereo-input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'large reference under build/')
    out.mkdir(parents=True, exist_ok=False)
    oracle = common.identity(ROOT / 'build/phase61/oracle_release_v1/phase61_frozen_reference')
    common.require(oracle['sha256'] == ORACLE_SHA, 'frozen oracle SHA')
    record = {'schema': 'performance-ab-fixed-references-v1', 'status': 'INCOMPLETE',
              'driver': common.identity(__file__), 'helper': common.identity(common.__file__),
              'reference_binary': oracle, 'reference_source_manifest': common.identity(ROOT / 'results/phase62_fix/recipes/oracle_manifest.json'),
              'expected_entries': 12, 'entries': [], 'independent_fixed_DSP': True, 'realtime_approval': False}
    common.save(out / 'REFERENCES.json', record)
    queries = [1440000, 1444800, 12960000, 12964800]
    for label, path, ch in (('mono48', a.mono_input, 1), ('stereo48', a.stereo_input, 2)):
        inp = common.wav_identity(path, 48000, ch)
        for speed in (400000, 1000000, 2000000):
            reused = label == 'mono48' and speed == 1000000
            folder = out / f'{label}_{speed}'
            folder.mkdir()
            if reused:
                old = ROOT / 'build/progressive_adoption_20261023_01/references_ab_01'
                for name, expected_sha in OLD_PINS.items():
                    common.require(common.identity(old / name)['sha256'] == expected_sha, 'old saved reference metadata SHA: ' + name)
                provenance = common.load(old / 'EXPECTED.json')
                common.require(provenance['input'] == {k: inp[k] for k in ('path', 'bytes', 'sha256')} and provenance['oracle'] == oracle and provenance['input_positions'] == queries, 'old reference provenance')
                cmd = provenance['command']
                raw, log = Path(cmd[4]), old / 'reference.log'
                common.require(common.identity(raw)['sha256'] == MONO_RAW_SHA, 'old mono RAW SHA')
            else:
                raw, log = folder / 'reference.f32', folder / 'oracle.log'
                cmd = [oracle['path'], inp['path'], str(speed), 'candidate', str(raw), *map(str, queries)]
                with log.open('w') as stdout, (folder / 'oracle.err').open('w') as stderr:
                    run = subprocess.run(cmd, stdout=stdout, stderr=stderr, timeout=180)
                common.require(run.returncode == 0, 'oracle failed')
            meta = common.load(log)
            raw_id = common.identity(raw)
            common.require(meta['sha256'] == raw_id['sha256'] and raw_id['bytes'] == meta['output_frames'] * ch * 4, 'RAW SHA/size')
            common.require(meta['channels'] == ch and meta['rate'] == 48000 and meta['input_frames'] == 14400000 and len(meta['positions']) == 4, 'reference dimensions')
            with raw.open('rb') as f:
                for block in iter(lambda: f.read(65536), b''):
                    common.require(len(block) % 4 == 0 and all(math.isfinite(v[0]) for v in struct.iter_unpack('<f', block)), 'NaN/Inf reference')
            for at, index in ((30, 0), (270, 2)):
                positions = queries[index:index + 2]
                mp = {**meta, 'input_positions': positions, 'positions': meta['positions'][index:index + 2], 'input_sha256': inp['sha256']}
                map_file = folder / f'A{at}_map.json'
                common.save(map_file, mp)
                old_meta = {}
                if reused:
                    old_map = old / f'A{at}_fresh_map.json'
                    old_map_values = common.load(old_map)
                    common.require(all(old_map_values[k] == mp[k] for k in ('output_frames', 'input_frames', 'channels', 'rate', 'sha256', 'positions', 'input_positions')), 'reused Map differs from saved oracle query')
                    old_meta = {'old_reference_map': common.identity(old_map), 'old_expected': common.identity(old / 'EXPECTED.json'),
                                'old_fixed_metadata_pins': OLD_PINS, 'old_map_values_identical': True}
                record['entries'].append({'id': f'{label}_A{at}_{speed}', 'input': {k: inp[k] for k in ('path', 'bytes', 'sha256')},
                    'preset': 'candidate', 'speed_micros': speed, 'input_positions': positions, 'queries': queries,
                    'raw': raw_id, 'map': common.identity(map_file), 'oracle_log': common.identity(log),
                    'command': cmd, 'returncode': 0, 'timeout': False, 'reused': reused,
                    'query_slice': [index, index + 1], 'finite': True, **old_meta})
            common.save(out / 'REFERENCES.json', record)
            print(label, speed, 'reference PASS', flush=True)
            common.require(common.identity(oracle['path']) == oracle and common.identity(inp['path'])['sha256'] == inp['sha256'], 'input/oracle changed')
    common.require(len(record['entries']) == 12, 'all reference IDs')
    record.update(status='PASS', complete=True)
    common.save(out / 'REFERENCES.json', record)


if __name__ == '__main__':
    main()
