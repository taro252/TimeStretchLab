"""DSPを含まない固定PCM/既存FIFOを直列比較し、全失敗を保持する。"""
import argparse
import csv
import json
import shutil
import subprocess
import time
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def analyze(folder):
    summary = json.loads((folder / 'summary.json').read_text())
    with (folder / 'callbacks.csv').open() as file:
        callbacks = list(csv.DictReader(file))
    jumps = []
    position_errors = []
    scale = summary['timebase_numer'] / summary['timebase_denom']
    for previous, current in zip(callbacks, callbacks[1:]):
        flags = int(previous['flags']) & int(current['flags'])
        sample_delta = float(current['sample_time']) - float(previous['sample_time']) if flags & 1 else None
        host_delta_ns = (int(current['host_ticks']) - int(previous['host_ticks'])) * scale if flags & 2 else None
        expected = int(previous['requested'])
        sample_error = sample_delta - expected if sample_delta is not None else None
        host_error = host_delta_ns - expected * 1e9 / 48000 if host_delta_ns is not None else None
        entry_delta_ns = (int(current['begin_ticks']) - int(previous['begin_ticks'])) * scale
        if (sample_error is not None and abs(sample_error) > 2) or (host_error is not None and abs(host_error) > 100000):
            jumps.append(dict(previous=previous, current=current, sample_delta=sample_delta,
                              extra_sample_frames=sample_error, host_delta_ns=host_delta_ns,
                              host_error_ns=host_error, entry_delta_ns=entry_delta_ns,
                              sample_and_host_progress_agree=(abs(sample_delta - host_delta_ns * 48000 / 1e9) <= 2)
                              if sample_delta is not None and host_delta_ns is not None else None,
                              initial_pair=int(current['sequence']) == 2))
        if int(current['logical_before']) != int(previous['logical_before']) + int(previous['received']):
            position_errors.append(dict(previous=previous, current=current))
    return dict(summary=summary, first_callbacks=callbacks[:5], clock_jumps=jumps,
                logical_position_errors=position_errors, physical_audio_continuity_verified=False,
                callback_signal_identical=summary['pcm_mismatches'] == 0 and not position_errors,
                artifacts=[dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p)) for p in folder.rglob('*') if p.is_file()])


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--tag', default='initial')
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--seconds', type=float, default=2)
    parser.add_argument('--binary', type=Path, default=ROOT/'build/phase59_fix2_sourcenode')
    args = parser.parse_args()
    assert 1 <= args.repeats <= 100 and .1 <= args.seconds <= 100
    out = OUT / ('minimal_' + args.tag); out.mkdir()
    data = ROOT / 'build/phase59_fix2_artifacts' / out.name; data.mkdir()
    binary = data / 'sourcenode_frozen'; shutil.copy2(args.binary, binary)
    manifest = dict(binary=str(binary), binary_sha256=sha(binary), script_sha256=sha(Path(__file__)),
                    repeats=args.repeats, seconds=args.seconds, callback_allocations_scope='C++ new全入口。C/Objective-C malloc全般は未計測。',
                    configurations=['A_direct', 'B_fifo_candidate', 'B_fifo_baseline'],
                    fifo_capacity=16384, candidate_lead=16384, baseline_lead=12288, block=2048,
                    operation='速度・装置設定は変えず、同じ48kHz Float32 stereo形式・ミキサー利得0.5。',
                    idle_caveat='試験間休止は装置全体のidle状態を証明しない。', free_before=shutil.disk_usage(ROOT).free)
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    rows = []
    for repeat in range(args.repeats):
        for mode, preset in [('direct','candidate'), ('fifo','candidate'), ('fifo','baseline')]:
            if shutil.disk_usage(ROOT).free < 4*1024**3:
                raise RuntimeError('容量下限。未開始条件を停止し、完了証拠を保持する。')
            folder = data / f'{repeat:03d}_{mode}_{preset}'
            command = [str(binary), mode, preset, str(args.seconds), str(folder)]
            started = time.time()
            with (data/(folder.name+'.log')).open('x') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=args.seconds+30)
            row = dict(repeat=repeat, mode=mode, preset=preset, command=command, exit=result.returncode,
                       wall_s=time.time()-started)
            if (folder/'summary.json').exists():
                row.update(analyze(folder))
            row['PASS'] = row['exit'] == 0 and bool(row.get('summary',{}).get('PASS'))
            rows.append(row)
            (out/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            print(repeat,mode,preset,'PASS' if row['PASS'] else 'FAIL',
                  'sample',row.get('summary',{}).get('sample_errors'),flush=True)
    summary = dict(sessions=len(rows), passed=sum(r['PASS'] for r in rows),
                   initial_clock_discontinuities=sum(j['initial_pair'] for r in rows for j in r.get('clock_jumps',[])),
                   direct_clock_discontinuities=sum(len(r.get('clock_jumps',[])) for r in rows if r['mode']=='direct'),
                   fifo_clock_discontinuities=sum(len(r.get('clock_jumps',[])) for r in rows if r['mode']=='fifo'),
                   missing_frames=sum(r.get('summary',{}).get('missing_frames',0) for r in rows),
                   failures_retained=True, root_cause_identified=False)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    assert sha(binary)==manifest['binary_sha256']
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
