"""固定180秒/2倍速の旧版・細分計測・負荷を直列比較する。"""
import argparse
import csv
import json
import math
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT, sha


def stats(values):
    values=sorted(values)
    if not values:return None
    return dict(n=len(values),median=statistics.median(values),p95=values[math.ceil(len(values)*.95)-1],
                p99=values[math.ceil(len(values)*.99)-1],max=max(values))


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--tag',default='before')
    parser.add_argument('--probe',type=Path,default=ROOT/'build/phase59_fix_fixed_probe')
    parser.add_argument('--focused-only',action='store_true')
    parser.add_argument('--reference',type=Path);parser.add_argument('--reference-json',type=Path)
    args=parser.parse_args()
    out=ROOT/'results/phase59_fix'/('phase_'+args.tag);out.mkdir()
    data=ROOT/'build/phase59_fix_artifacts'/('phase_'+args.tag);data.mkdir()
    probe=data/'fixed_probe';shutil.copy2(args.probe,probe)
    source=ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'
    oracle=ROOT/'build/phase58_frozen/product_reference';raw=args.reference or data/'reference.f32'
    if args.reference:
        assert args.reference_json
        reference=json.loads(args.reference_json.read_text())
    else:
        command=[str(oracle),str(source),'2000000','candidate',str(raw)]
        result=subprocess.run(command,capture_output=True,text=True,check=True,timeout=600)
        reference=json.loads(result.stdout)
    assert sha(raw)==reference['pcm_sha256']
    (out/'reference.json').write_text(json.dumps(reference,indent=2)+'\n')
    versions={'probe':probe,'phase58_fix':ROOT/'build/phase58_fix_frozen/candidate_v3_native',
              'phase59_final':ROOT/'build/phase59_frozen/final/phase58_native'}
    plan=[('probe',preset,2,'detail') for preset in ['candidate','baseline']]
    if not args.focused_only:
        for label,cpu,profile in [('phase58_fix',2,'block'),('phase59_final',0,'block'),
                                  ('phase59_final',2,'off'),('probe',0,'detail'),('phase59_final',2,'block')]:
            plan += [(label,preset,cpu,profile) for preset in ['candidate','baseline']]
    manifest=dict(input=str(source),input_sha256=sha(source),speed=2000000,reference_sha256=sha(raw),
        oracle_sha256=sha(oracle),binaries={k:dict(path=str(v),sha256=sha(v)) for k,v in versions.items()},
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*') if p.is_file()},
        plan=plan,artifact_directory=str(data),minimum_free_bytes=2*1024**3,
        phase_stages={'20':'joint spectrum+peak inclusive','21':'shared peak analysis','23':'one channel vocoder','24':'stereo coherence'},
        scope='計算式は変更せず細分計測・固定個数の計数だけを追加。従来CSVの集約phase値と二重加算しない。')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n');rows=[]
    for index,(label,preset,cpu,profile) in enumerate(plan):
        if shutil.disk_usage(ROOT).free<manifest['minimum_free_bytes']+64*1024**2:raise RuntimeError('Disk floor reached')
        folder=data/f'{index:02d}_{label}_{preset}_cpu{cpu}_{profile}'
        command=[str(versions[label]),str(source),'2000000',preset,str(raw),str(reference['output_frames']),reference['pcm_sha256'],str(folder),
            'normal','0',str(cpu),'0','0','0','--worker=workgroup','--resident-input=on','--profile='+profile,'--sample-thread=on']
        if label=='probe' and profile=='detail':
            command += ['--phase-probe=335872:350208','--phase-probe=3186688:3201024','--phase-probe=3430400:3448832']
        started=time.time()
        with (data/f'{index:02d}.log').open('x') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        summary=json.loads((folder/'summary.json').read_text());worker=list(csv.DictReader((folder/'worker.csv').open()))
        realtime=[r for r in worker if r['realtime']=='1']
        row=dict(index=index,label=label,preset=preset,cpu=cpu,profile=profile,command=command,exit=result.returncode,native=summary,
            wall_s=time.time()-started,pcm_complete_exact=bool(summary['pcm_complete_exact']),
            realtime_cpu_ms=stats([float(r['cpu_s'])*1000 for r in realtime]),
            realtime_wall_ms=stats([float(r['wall_s'])*1000 for r in realtime]),
            phase_cpu_ms=stats([float(r['phase_cpu_s'])*1000 for r in realtime]),
            worst_blocks=sorted(realtime,key=lambda r:float(r['cpu_s']),reverse=True)[:10])
        intervals=folder/'intervals.csv'
        if intervals.exists():
            records=list(csv.DictReader(intervals.open()));row['deadline_intervals']=[r for r in records if r['deadline_miss']=='1']
            assert len(row['deadline_intervals'])==summary['workgroup_deadline_misses']
        row['artifacts']=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in folder.rglob('*') if p.is_file()]
        rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(index,label,preset,cpu,profile,'exit',result.returncode,'deadline',summary['workgroup_deadline_misses'],'PCM',row['pcm_complete_exact'],flush=True)
    (out/'summary.json').write_text(json.dumps(dict(sessions=len(rows),passed=sum(bool(r['native']['PASS']) for r in rows),all_pcm_exact=all(r['pcm_complete_exact'] for r in rows)),indent=2)+'\n')


if __name__=='__main__':main()
