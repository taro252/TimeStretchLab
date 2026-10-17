"""ユーザー音源のStop→PlayをA/B/B/Aで測定。各segmentは意図したprefix停止。"""
import hashlib,json,subprocess,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    full=json.loads((ROOT/'results/phase60/native_user_canonical/summary.json').read_text())
    assert full['measurement_completed'],'Wait for full-file tests before this audio batch'
    data=ROOT/'build/phase60/native_user_restart';data.mkdir(exist_ok=False);out=ROOT/'results/phase60/native_user_restart';out.mkdir(exist_ok=False)
    source=Path(json.loads((ROOT/'results/phase60/INPUT.json').read_text())['wav']);binary=ROOT/'build/phase60_playback_compare';legacy=ROOT/'build/phase60/approved_legacy/release/phase60_legacy_compare';binaries={str(p):sha(p) for p in (binary,legacy)}
    actions=data/'actions.csv';actions.write_text('at_s,action,value\n10.0,stop_play,0\n20.0,stop,0\n')
    rows=[]
    for index,engine in enumerate(('legacy','progressive','progressive','legacy')):
        if shutil.disk_usage(ROOT).free<8*1024**3:raise RuntimeError('Disk floor')
        for p,h in binaries.items():assert sha(p)==h
        name=f'{index}_{engine}';folder=data/name;cmd=[str(binary),str(source),'--engine='+engine,'--speed=1.00','--preset=candidate','--actions='+str(actions),'--out='+str(folder)]
        print(name,'開始',flush=True);started=time.time()
        with (data/(name+'.log')).open('x') as log:
            try:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=240);code=r.returncode
            except subprocess.TimeoutExpired:code=124
        row={'name':name,'engine':engine,'command':cmd,'exit':code,'wall_s':time.time()-started,'summary':json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else None}
        rows.append(row);(out/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n');(out/'driver.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,code,flush=True)
    summaries=[r['summary'] for r in rows if r['summary']]
    result={'measurement_completed':len(summaries)==4 and all(len(s['sessions'])==2 for s in summaries),'prefix_only':True,'natural_eos_claimed':False,'binaries':binaries,'input_sha256':sha(source),'rows':rows}
    result['stop_play_pass']=result['measurement_completed'] and all(r['exit']==0 and r['summary']['supply_and_callback_pass'] and all(s['native']['first_pcm_mach_ns']>0 for s in r['summary']['sessions']) and r['summary']['sessions'][0]['session']!=r['summary']['sessions'][1]['session'] for r in rows)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return 0 if result['stop_play_pass'] else 2
if __name__=='__main__':raise SystemExit(main())
