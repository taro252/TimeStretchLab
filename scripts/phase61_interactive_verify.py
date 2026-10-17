"""Interactive native comparisons and focused regressions. Never overwrites evidence.

Run after Release/Debug builds finish, with native audio access. All subprocesses
are sequential to avoid concurrent audio hosts and benchmark CPU interference.
"""
import argparse, hashlib, json, shutil, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--suite', choices=['native', 'regression', 'interactive'], required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); out = a.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    build = ROOT/'build/phase61_interactive_seek'
    release, debug = build/'release', build/'debug'
    mono = ROOT/'results/phase56/long/chain_300s.wav'
    stereo = ROOT/'build/phase61_fast_seek/music_300s.wav'
    fixtures = [ROOT/'build/phase61/native_inputs'/f'boundary_{r}_{c}.wav' for r,c in [(48000,2),(44100,1)]]
    commands = []
    def run(name, command, timeout=1800):
        if shutil.disk_usage(ROOT).free < 4*1024**3:
            raise RuntimeError('Free disk below 4GiB; no evidence removed')
        command = list(map(str, command)); start = time.monotonic()
        print('BEGIN', name, flush=True)
        with (out/(name+'.log')).open('x') as log:
            try: result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, timeout=timeout).returncode
            except subprocess.TimeoutExpired: result = -1
        commands.append({'name':name,'command':command,'exit':result,'wall_s':time.monotonic()-start,'log':str(out/(name+'.log'))})
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        print('END', name, result, commands[-1]['wall_s'], flush=True)
    if a.suite == 'interactive':
        for mode, directory in [('release',release),('debug',debug)]:
            for fixture in fixtures:
                name=mode+'_'+fixture.stem
                run('controls64_'+name,[directory/'phase61_interactive_native_tests',fixture,out/('controls64_'+name),'--controls64'])
        run('controls512_release',[release/'phase61_interactive_native_tests',fixtures[0],out/'controls512_release','--controls'])
        for name, source in [('mono',mono),('stereo',stereo)]:
            run('baseline_'+name,[build/'baseline_matched_v3/phase61_interactive_native_tests',source,out/('baseline_'+name)])
            run('performance_'+name,[release/'phase61_interactive_native_tests',source,out/('performance_'+name)])
        run('early_stereo',[release/'phase61_interactive_native_tests',stereo,out/'early_stereo','--early'])
        for mode,directory in [('release',release),('debug',debug)]:
            run('exact_'+mode,[directory/'phase61_native_tests',fixtures[0],out/('exact_'+mode)])
            run('lifecycle_'+mode,[directory/'phase60_lifecycle_tests',ROOT/'results/phase31/input/mix.wav'])
    elif a.suite == 'native':
        for name, source in [('mono',mono),('stereo',stereo)]:
            run('performance_'+name, [release/'phase61_interactive_native_tests',source,out/('performance_'+name)])
        run('early_stereo',[release/'phase61_interactive_native_tests',stereo,out/'early_stereo','--early'])
        for mode, directory in [('release',release),('debug',debug)]:
            for fixture in fixtures:
                name = mode+'_'+fixture.stem
                run('controls_'+name,[directory/'phase61_interactive_native_tests',fixture,out/('controls_'+name),'--controls'])
                run('exact_'+name,[directory/'phase61_native_tests',fixture,out/('exact_'+name)])
            run('lifecycle_'+mode,[directory/'phase60_lifecycle_tests',ROOT/'results/phase31/input/mix.wav'])
    else:
        for mode, directory in [('release',release),('debug',debug)]:
            run('ctest_'+mode,['ctest','--test-dir',directory,'-R','^(phase54_|phase56_|phase57_|phase58_|phase59_|phase60_|phase61_)','--output-on-failure','-j1'])
        run('golden',['python3','-B',ROOT/'tests/Phase61Golden.py','--probe',release/'phase54_core_probe','--output',out/'golden'])
        # The source DSP isn't changed; this full Exact matrix additionally
        # uses the explicitly frozen, pre-Phase61 reference executable.
        run('exact_full_release',['python3','-B',ROOT/'tests/Phase61SeekSmoke.py',release/'phase61_seek_check',ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference','--full','--output',out/'exact_full_release'])
    manifest = {'suite':a.suite,'commands':commands,'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'release_native_sha256':hashlib.sha256((release/'phase61_interactive_native_tests').read_bytes()).hexdigest(),
                'debug_native_sha256':hashlib.sha256((debug/'phase61_interactive_native_tests').read_bytes()).hexdigest()}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return int(any(c['exit'] for c in commands))

if __name__ == '__main__':
    raise SystemExit(main())
