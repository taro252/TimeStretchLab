"""EOS診断のMach区間とOSトレースを対応付け、未観測を明記する。"""
import argparse
import csv
import json
import subprocess
from pathlib import Path
from phase57_study import sha
from phase58_fix_trace_analyze import SCHEMAS,complete_export,table,number,IntervalIndex,classify


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--sessions',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir();xml=out/'xml';xml.mkdir()
    exports=[]
    for schema in SCHEMAS:
        path=xml/(schema+'.xml')
        command=['xcrun','xctrace','export','--input',str(args.trace.resolve()),'--xpath','/trace-toc/run[@number="1"]/data/table[@schema="'+schema+'"]']
        with path.open('x') as file,(out/(schema+'_export.log')).open('x') as log:p=subprocess.run(command,stdout=file,stderr=log,timeout=180)
        assert p.returncode==0 and complete_export(path),schema
        exports.append(dict(command=command,path=str(path),bytes=path.stat().st_size,sha256=sha(path)))
    clocks=table(xml/'time-info.xml');assert clocks,'Missing Mach epoch; no inferred alignment'
    clock=clocks[0];numer,denom=map(int,clock['timebase-info']['fmt'].split('/'))
    epoch=number(clock,'mabs-epoch')*numer/denom
    summaries=list(csv.DictReader((args.sessions/'summary.csv').open()))
    tids={int(r['dsp_thread']) for r in summaries}
    states=table(xml/'thread-state.xml',tids);calls=table(xml/'syscall.xml',tids);faults=table(xml/'virtual-memory.xml',tids)
    results=[]
    for session in summaries:
        tid=int(session['dsp_thread']);run=session['run']
        indexes=[IntervalIndex([r for r in records if r['thread']['tid']==tid]) for records in (states,calls,faults)]
        blocks=[]
        for block in csv.DictReader((args.sessions/('worker_'+run+'.csv')).open()):
            if block['realtime']!='1':continue
            start=int(block['start_ticks'])*numer/denom-epoch;end=int(block['end_ticks'])*numer/denom-epoch
            os=classify(start,end,*indexes)
            known=os['unobserved_s']<1e-9 and os['state_seconds'].get('Unknown',0)<1e-9
            blocks.append(dict(**block,os=os,fully_known=known))
        result=dict(run=run,summary=session,realtime_blocks=len(blocks),fully_known=sum(b['fully_known'] for b in blocks),
            unknown_or_unobserved=sum(not b['fully_known'] for b in blocks),
            worst_non_cpu=sorted(blocks,key=lambda b:float(b['wall_s'])-float(b['cpu_s']),reverse=True)[:10])
        (out/('blocks_'+run+'.json')).write_text(json.dumps(blocks,indent=2)+'\n');results.append(result)
    (out/'summary.json').write_text(json.dumps(dict(trace_epoch_ns=epoch,timebase=dict(numer=numer,denom=denom),exports=exports,sessions=results,
        scope='実際の区間開始/終了Mach ticksを使用。Unknown/未観測をRunningへ補完しない。区間外の状態から原因を推測しない。'),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
