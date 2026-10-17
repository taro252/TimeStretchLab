"""Check pre-transition native RAW against the unchanged offline local DSP.

This is an integration/order oracle, NOT the independent full-render quality
screen. Post-mix PCM is separately verified by the native callback observer.
"""
import argparse, hashlib, json, math, struct, subprocess
from pathlib import Path

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--sessions',type=Path,required=True);p.add_argument('--study',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    data=a.source.read_bytes();at=12;fmt=None;size=None
    while at+8<=len(data):
        kind,n=struct.unpack_from('<4sI',data,at);at+=8
        if kind==b'fmt ':fmt=struct.unpack_from('<HHIIHH',data,at)
        if kind==b'data':size=n
        at+=n+n%2
    rate,ch=fmt[2],fmt[1];frames=size//fmt[4];del data
    cache={};rows=[];commands=[]
    for folder in sorted(a.sessions.iterdir()):
        if not folder.is_dir() or not (folder/'captures.json').exists():continue
        kind=folder.name.split('_',1)[1];preset=folder.name.split('_',1)[0]
        ops=json.loads((folder/'seeks.json').read_text());caps=json.loads((folder/'captures.json').read_text())
        for op in ops:
            if op['state']!='Completed':continue
            speed=op.get('speed',400000 if kind=='speed_prepare' else 500000)
            key=(speed,op['input']);directory=out/f'{speed}_{op["input"]}'
            if key not in cache:
                cmd=list(map(str,[a.study.resolve(),a.source.resolve(),directory,speed,rate//2,op['input'],math.ceil(frames*2.5),1,'local']))
                run=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
                (out/f'{speed}_{op["input"]}.log').write_text(run.stdout+run.stderr)
                commands.append({'command':cmd,'exit':run.returncode})
                if run.returncode:raise RuntimeError(run.stderr)
                cache[key]={r['candidate']:r for r in map(json.loads,run.stdout.splitlines())}
            expected_row=cache[key][preset=='candidate'];expected=(directory/(expected_row['name']+'.f32')).read_bytes()
            cap=next((c for c in caps if c['epoch']==op['epoch']),None)
            if op['input']==frames:
                good=not cap and not expected and op['output']==expected_row['output_start']
                rows.append({'session':folder.name,'epoch':op['epoch'],'scope':'empty_suffix','PASS':good});continue
            if cap is None:raise RuntimeError('Completed nonempty epoch has no RAW: '+folder.name)
            actual=Path(cap['path']).read_bytes();dynamic=kind in ('speed_after','speed_started')
            limit=min(len(actual),rate//10*ch*4) if dynamic else len(actual)
            complete=kind in ('ready','playing','paused','eof_paused')
            good=cap['start']==op['output']==expected_row['output_start'] and actual[:limit]==expected[:limit]
            if complete:good &= len(actual)==len(expected)
            rows.append({'session':folder.name,'epoch':op['epoch'],'scope':'full_suffix' if complete else 'prefix',
                         'frames':len(actual)//(ch*4),'compared_frames':limit//(ch*4),'expected_frames':len(expected)//(ch*4),
                         'raw_sha256':sha(cap['path']),'local_reference_sha256':hashlib.sha256(expected).hexdigest(),'PASS':good})
    result={'PASS':bool(rows) and all(r['PASS'] for r in rows),'rows':rows,'commands':commands,'input_sha256':sha(a.source),
            'study_sha256':sha(a.study),'driver_sha256':sha(__file__),
            'oracle':'unchanged offline local DSP, NO publication fade, NOT independent quality reference',
            'full_suffix':sum(r['scope']=='full_suffix' and r['PASS'] for r in rows),
            'prefix':sum(r['scope']=='prefix' and r['PASS'] for r in rows),
            'empty_suffix':sum(r['scope']=='empty_suffix' and r['PASS'] for r in rows)}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('commands','rows')}));return 0 if result['PASS'] else 2

if __name__=='__main__':raise SystemExit(main())
