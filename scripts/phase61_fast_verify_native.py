"""Verify captured native Fast PCM against the offline local origin + 5ms fade.

This is integration verification, not an independent quality oracle. The study
driver separately compares local output with the frozen full-render reference.
"""
import argparse,hashlib,json,math,subprocess
from pathlib import Path
import numpy as np
from phase61_fast_seek_study import wav_info,sha

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--sessions',type=Path,required=True)
    p.add_argument('--study',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);rate,ch,n=wav_info(a.input);cache={};rows=[];commands=[]
    for session in sorted(a.sessions.iterdir()):
        if not session.is_dir(): continue
        captures=json.loads((session/'captures.json').read_text());seeks=json.loads((session/'seeks.json').read_text())
        for capture in captures:
            operation=next((s for s in seeks if s['epoch']==capture['epoch'] and s['state']=='Completed'),None)
            if operation is None: continue
            key=(operation['speed'],operation['input'])
            if key not in cache:
                directory=out/f'{key[0]}_{key[1]}'
                cmd=list(map(str,[a.study.resolve(),a.input.resolve(),directory,key[0],rate//2,key[1],math.ceil(n*2.5),1,'local']))
                result=subprocess.run(cmd,capture_output=True,text=True);commands.append({'command':cmd,'exit':result.returncode})
                (out/f'{key[0]}_{key[1]}.log').write_text(result.stdout+result.stderr)
                if result.returncode: raise RuntimeError(result.stderr)
                cache[key]=directory
            preset=session.name.split('_',1)[0]
            expected=np.fromfile(cache[key]/f'{key[0]}_{preset}_{rate//2}_{key[1]}_0.f32',dtype='<f4').reshape(-1,ch)
            curve=np.array([.5-.5*math.cos(math.pi*i/(rate//200-1)) for i in range(rate//200)],dtype=np.float32)
            expected[:min(len(curve),len(expected))]*=curve[:min(len(curve),len(expected)),None]
            actual=np.fromfile(Path(capture['path']),dtype='<f4').reshape(-1,ch)
            prefix=min(len(actual),rate//10);prefix_ok=bool(np.array_equal(actual[:prefix].view('<u4'),expected[:prefix].view('<u4')))
            kind=session.name.split('_',1)[1];last=capture['epoch']==max((s['epoch'] for s in seeks),default=0)
            full=last and kind not in ('speed_after','stop','route')
            full_ok=bool(np.array_equal(actual.view('<u4'),expected.view('<u4'))) if full else None
            ok=capture['start']==operation['output'] and prefix_ok and (full_ok is not False)
            rows.append({'session':session.name,'epoch':capture['epoch'],'input':operation['input'],'output':capture['start'],'prefix_frames':prefix,'prefix_match':prefix_ok,'full_suffix':full,'full_suffix_match':full_ok,'actual_frames':len(actual),'expected_frames':len(expected),'capture_sha256':sha(capture['path']),'PASS':ok})
    summary={'PASS':bool(rows) and all(r['PASS'] for r in rows),'captures':len(rows),'full_suffix_checks':sum(r['full_suffix'] for r in rows),'prefix_checks':len(rows),'integration_oracle':'offline local DSP plus worker fade, NOT independent full render','input_sha256':sha(a.input),'study_sha256':sha(a.study),'commands':commands,'rows':rows}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k not in ('commands','rows')}));return 0 if summary['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())
