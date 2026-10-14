#!/usr/bin/env python3
"""Actual worker with virtual consumer; never a realtime performance PASS."""
import csv,json,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51/busy'
def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=OUT);args=parser.parse_args();output=args.output
    output.mkdir(parents=True,exist_ok=True)
    if (output/'summary.json').exists():raise SystemExit('Fresh output required')
    scenarios=[(.4,'2,.4'),(.4,'1,2'),(2,'.4,1.5'),(.4,'2,.75,1.5')];rows=[]
    cases=[(i,s,'latest') for i in (100,200,400,800,1500) for s in scenarios]
    cases += [(200,scenarios[-1],p) for p in ('defer','continue')]
    for ordinal,(interval,(initial,targets),policy) in enumerate(cases,1):
        path=output/f'{ordinal:02d}_{interval}_{policy}';path.mkdir()
        input=ROOT/'results/phase31/input/drums.wav'
        args=[ROOT/'build/phase51_busy_study',input,path,initial,targets,interval/1000,policy,'L2',512]
        result=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=180);(path/'study.log').write_text(result.stdout+result.stderr);assert result.returncode==0
        ref=subprocess.run(list(map(str,[ROOT/'build/phase51_reference',input,path/'reference.wav',initial,path/'replay.csv','L2','safe-density'])),capture_output=True,text=True,timeout=180);(path/'reference.log').write_text(ref.stdout+ref.stderr);assert ref.returncode==0
        hashes=[hashlib.sha256((path/name).read_bytes()).hexdigest() for name in ('raw.wav','reference.wav')];assert hashes[0]==hashes[1]
        operations=list(csv.DictReader((path/'operations.csv').open()));gens=[int(o['generation']) for o in operations if int(o['generation'])];assert gens==sorted(set(gens))
        assert all(o['state'] in ('Completed','Duplicate','Rejected','Replaced','BusyRejected','Stopped') for o in operations)
        rows.append(dict(ordinal=ordinal,interval_ms=interval,initial=initial,targets=targets,policy=policy,operations=operations,PCM_CORRECTNESS='PASS',sha256=hashes[0],REALTIME='NOT_TESTED'))
        (output/'summary.json').write_text(json.dumps(rows,indent=2));print(ordinal,interval,initial,targets,policy,'PCM PASS',flush=True)
if __name__=='__main__':main()
