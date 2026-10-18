"""Focused sync/restart verification. Separate builds and never overwrite results.

Native suites require output-device access and run hosts sequentially. Build
the targets listed by --suite targets in each supplied build directory first.
ThreadSanitizer is deliberately separate from real audio and Release timing.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = '''phase54_analysis_tests phase54_seek_tests phase54_core_probe
phase56_tests phase56_fixed_modes phase56_check phase56_reference
phase57_tests phase57_check phase57_reference
phase58_tests phase58_check phase58_product_reference phase58_fix_tests
phase58_fix_mailbox_tests phase58_fix_worker_tests phase59_tests phase59_reference
phase59_check phase59_progressive_replay phase59_captured_reference
phase59_control_tests phase59_fix_vocoder_tests phase59_fix_stereo_tests
phase60_contract_tests phase60_lifecycle_tests phase61_contract_tests
phase61_fast_seek_tests phase61_fast_seek_study phase61_safety_tests
phase61_checkpoint_tests phase61_seek_check phase61_seek_reference
phase61_output_transition_tests phase61_pipeline_sync_tests
phase61_sync_restart_native_tests phase61_interactive_native_tests
phase61_interactive_eof_tests phase61_native_tests'''.split()

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--suite', choices=['targets', 'local', 'native', 'regression', 'performance'], required=True)
    p.add_argument('--release', type=Path)
    p.add_argument('--debug', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.suite == 'targets':
        print(' '.join(TARGETS))
        return 0
    assert a.release and a.debug and a.output
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    builds = [('release', a.release.resolve()), ('debug', a.debug.resolve())]
    fixtures = [ROOT/'build/phase61/native_inputs'/f'boundary_{r}_{c}.wav' for r,c in [(48000,2),(44100,1)]]
    commands = []
    def run(name, command, timeout=1800):
        command = list(map(str, command))
        print('BEGIN', name, flush=True)
        began = time.monotonic()
        with (out/(name+'.log')).open('x') as log:
            try:
                code = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                code = -1
        commands.append(dict(name=name, command=command, exit=code, wall_s=time.monotonic()-began))
        (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        print('END', name, code, flush=True)
    if a.suite == 'local':
        for mode,b in builds:
            for fixture in fixtures:
                name = mode+'_'+fixture.stem
                run('sync_'+name, [b/'phase61_sync_restart_native_tests', fixture, out/('sync_'+name)], 300)
        run('physical_release', [builds[0][1]/'phase61_sync_restart_native_tests',fixtures[0],out/'physical_release','--physical'], 180)
    elif a.suite == 'native':
        for mode,b in builds:
            for fixture in fixtures:
                name = mode+'_'+fixture.stem
                run('controls64_'+name, [b/'phase61_interactive_native_tests', fixture, out/('controls64_'+name), '--controls64'], 600)
                run('eof_'+name, [b/'phase61_interactive_eof_tests', fixture, out/('eof_'+name)], 120)
            run('lifecycle_'+mode, [b/'phase60_lifecycle_tests', ROOT/'results/phase31/input/mix.wav'], 120)
    elif a.suite == 'regression':
        for mode,b in builds:
            run('ctest_'+mode, ['ctest','--test-dir', b, '-R','^(phase54_|phase56_|phase57_|phase58_|phase59_|phase60_|phase61_)','--output-on-failure','-j1'])
        run('golden', ['python3','-B',ROOT/'tests/Phase61Golden.py','--probe',builds[0][1]/'phase54_core_probe','--output',out/'golden'])
        run('exact_full_release', ['python3','-B',ROOT/'tests/Phase61SeekSmoke.py',builds[0][1]/'phase61_seek_check',ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference','--full','--output',out/'exact_full_release'])
    elif a.suite == 'performance':
        for name,source in [('mono', ROOT/'results/phase56/long/chain_300s.wav'), ('stereo',ROOT/'build/phase61_fast_seek/music_300s.wav')]:
            run(name,[builds[0][1]/'phase61_interactive_native_tests',source,out/name],600)
    return int(any(c['exit'] for c in commands))

if __name__ == '__main__':
    raise SystemExit(main())
