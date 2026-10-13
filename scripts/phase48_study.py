#!/usr/bin/env python3
"""Serial interleaved native A/B/C study. Never trace or compare DSP in parallel."""
import argparse,hashlib,json,os,platform,subprocess,time
from pathlib import Path
from phase46_native import run
from phase48_metrics import measure,save_summaries
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'results/phase48/study')
    p.add_argument('--source',choices=('drums','mix'),default='drums');p.add_argument('--minutes',type=int,default=3)
    p.add_argument('--no-stress',action='store_true');p.add_argument('--orders',default='ABC,CBA,BCA,ACB')
    args=p.parse_args();orders=args.orders.split(',');assert all(set(s)<=set('ABC') and s for s in orders)
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'study_manifest.json').exists():raise SystemExit('Use a new output directory; study evidence already exists')
    source=ROOT/('results/phase40/long_input' if args.source=='drums' else 'results/phase14/benchmark')/f'{args.source}_repeat_{args.minutes*60}.wav'
    manifest=dict(base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),build='Release arm64',
        executable_sha256=hashlib.sha256((ROOT/'build/phase43_play').read_bytes()).hexdigest(),
        input_path=str(source),input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        schedule_sha256=hashlib.sha256((ROOT/'results/phase45/repeated.csv').read_bytes()).hexdigest(),
        orders=orders,system=platform.platform(),macos=platform.mac_ver(),stress_threads=0 if args.no_stress else 2,
        trace=False,callback_target=512,initial_speed=.4,schedule='output 1/6/14/22 sec -> 2/.4/1/2',fifo=16384,lead=12288,
        qos_B='USER_INITIATED, relative priority 0; render thread unchanged',block_A_B=2048,block_C=1024,
        logical_cpus=os.cpu_count(),note='No CTest, reference synthesis, or trace runs concurrently with native playback. Reference synthesis only after each playback.')
    (args.output/'study_manifest.json').write_text(json.dumps(manifest,indent=2));rows=[]
    for round_index,order in enumerate(orders,1):
        for candidate in order:
            ordinal=len(rows)+1;fs=os.statvfs(args.output)
            context=dict(ordinal=ordinal,round=round_index,order=order,disk_free_before_bytes=fs.f_bavail*fs.f_frsize)
            if context['disk_free_before_bytes']<fs.f_blocks*fs.f_frsize*.05:raise SystemExit('Insufficient storage reserve; remaining native trials stopped')
            print(f'BEGIN {ordinal}/{sum(map(len,orders))} round={round_index} candidate={candidate}',flush=True)
            row,path=run(args.output,args.source,args.minutes,trace=False,stress=not args.no_stress,candidate=candidate)
            result=measure(row,path,context);rows.append(result);save_summaries(args.output,rows)
            print(f'END {ordinal} {candidate} {result["NATIVE_STABILITY_VERDICT"]} missing={result.get("underrun_frames")} measurement={result["MEASUREMENT_QUALITY"]}',flush=True)
            time.sleep(2)
    print('A/B/C native study complete; all outcomes retained',flush=True)
    verdict='FAIL' if any(r['NATIVE_STABILITY_VERDICT']=='FAIL' for r in rows) else 'INDETERMINATE' if any(r['NATIVE_STABILITY_VERDICT']!='PASS' for r in rows) else 'PASS'
    print(f'EXPERIMENT_EXECUTION=COMPLETE NATIVE_QUALITY={verdict}',flush=True)
    if verdict!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
