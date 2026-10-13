#!/usr/bin/env python3
"""Offline candidate proof before native testing; this consumer is not realtime."""
import csv,hashlib,json,os,subprocess
from pathlib import Path
from phase45_store import parse_log
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase50/l1_offline'
def command(args,log,env=None):
    r=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,text=True,env=env,timeout=180)
    log.write_text(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError(str(log))
    return parse_log(r.stdout)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'summary.json').exists():raise SystemExit('Fresh output required')
    rows=[]
    # Two timings, four directions per real source; full history plus repeated hops.
    for source in ('mix','drums'):
        input=ROOT/('results/phase50/input/mix30.wav' if source=='mix' else 'results/phase49/input/drums30.wav')
        for time in (1,1.6):
            schedule=','.join(f'{at+time-1}:{speed}' for at,speed in [(1,2),(6,.4),(14,1),(22,2)])
            for label in ('legacy','L1'):
                path=OUT/f'{source}_{time}_{label}';path.mkdir()
                env=os.environ.copy();env.pop('PHASE50_PRECISE_BOUNDARY',None)
                if label=='L1':env['PHASE50_PRECISE_BOUNDARY']='1'
                info=command([ROOT/'build/phase50_sim',input,path/'raw.wav',.4,schedule,512,path/'replay.csv',2048,'C','safe-density',path/'workers.csv'],path/'sim.log',env)
                command([ROOT/'build/phase39_reference',input,path/'reference.wav',.4,path/'replay.csv','C','safe-density'],path/'reference.log')
                pcm=command([ROOT/'build/phase45_pcm_hash',path/'raw.wav',path/'reference.wav'],path/'compare.log')
                plans=list(csv.DictReader((path/'replay.csv').open()))
                assert all(p['state_preserved']=='1' for p in plans)
                assert pcm['first_changed_pcm_frame']=='none'
                assert hashlib.sha256((path/'raw.wav').read_bytes()).digest()==hashlib.sha256((path/'reference.wav').read_bytes()).digest()
                # Independent full final history equals incremental synthesis. This
                # includes already returned PCM, not only a prefix of requested length.
                row=dict(source=source,time=time,label=label,PCM_CORRECTNESS='PASS',info=info,plans=plans,pcm=pcm)
                rows.append(row);(OUT/'summary.json').write_text(json.dumps(rows,indent=2))
                print(source,time,label,'PASS',flush=True)
if __name__=='__main__':main()
