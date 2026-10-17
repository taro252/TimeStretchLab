"""実機A/Bを直列実行し、停止後に固定された独立参照とPCMを比較する。"""
import argparse,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def summarize(rows,expected_executions,expected_pcm):
    captures=[r for r in rows if r.get('summary')]
    complete=len(captures)==expected_executions and all(r['exit'] in (0,2) for r in rows)
    pcm=[r['pcm'] for r in captures if 'pcm' in r]
    return {'measurement_completed':complete,'executions':len(captures),'sessions':sum(len(r['summary']['sessions']) for r in captures),'supply_and_callback_pass':complete and all(r['summary']['supply_and_callback_pass'] for r in captures),'progressive_worker_deadlines_pass':complete and all(s.get('worker_deadline_misses')==0 for r in captures if r['summary']['engine']=='progressive' for s in r['summary']['sessions']),'pcm_cases':len(pcm),'pcm_pass':complete and len(pcm)==expected_pcm and all(r['PASS'] for r in pcm),'failures':[r['name'] for r in rows if r['exit']!=0 or r.get('pcm',{}).get('PASS') is False],'rows':rows}
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--suite',choices=['representative','user'],required=True);p.add_argument('--tag',default='');args=p.parse_args()
    if args.tag and not all(c.isalnum() or c in '-_' for c in args.tag):raise ValueError('Invalid tag')
    assert json.loads((ROOT/'results/phase60/QUALITY.json').read_text())['PASS'],'Complete offline quality first'
    label='native_'+args.suite+('_'+args.tag if args.tag else '')
    data=ROOT/'build/phase60'/label;data.mkdir(exist_ok=False);output=ROOT/'results/phase60'/label;output.mkdir(exist_ok=False)
    binary=ROOT/'build/phase60_playback_compare';legacy=ROOT/'build/phase60/approved_legacy/release/phase60_legacy_compare';reference=ROOT/'build/phase58_frozen/product_reference';captured=ROOT/'build/phase59_frozen/captured_reference'
    binaries={str(x):sha(x) for x in (binary,legacy,reference,captured)}
    source_manifest={str(x.relative_to(ROOT)):sha(x) for d in ('src','examples') for x in (ROOT/d).rglob('*') if x.is_file() and x.name!='.DS_Store'}
    source_manifest['CMakeLists.txt']=sha(ROOT/'CMakeLists.txt')
    manifest={'binaries':binaries,'source_sha256':source_manifest,'driver_sha256':sha(Path(__file__)),'host':subprocess.check_output(['sw_vers'],text=True),'architecture':subprocess.check_output(['uname','-m'],text=True).strip(),'configuration':'Release arm64','simultaneous_audio':False,'build_or_other_dsp_during_audio':False,'source_device_rates_separate':True,'user_original_merodoa_wav_identical':None,'os_cache_purged':False}
    manifest['fixture_generator_sha256']=sha(ROOT/'scripts/phase57_study.py')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');rows=[]
    def run(name,cmd,timeout):
        if shutil.disk_usage(ROOT).free<8*1024**3:raise RuntimeError('Disk floor 8GiB')
        for path,expected in binaries.items():assert sha(path)==expected,'Binary changed: '+path
        command=list(map(str,cmd));started=time.time()
        (output/'RUNNING.json').write_text(json.dumps({'name':name,'command':command,'started_unix':started},indent=2)+'\n');print(name,'開始',flush=True)
        with (data/(name+'.log')).open('x') as log:
            try:r=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout);exit=r.returncode
            except subprocess.TimeoutExpired:exit=124
        entry={'name':name,'command':command,'exit':exit,'wall_s':time.time()-started,'log':str(data/(name+'.log'))};rows.append(entry)
        (output/'driver.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,exit,flush=True);return entry
    def compare(name,source,engine,preset='candidate',speed=1,actions=None,verify=False,dynamic=False):
        folder=data/name;capture=data/(name+'.f32')
        cmd=[binary,source,'--engine='+engine,'--preset='+preset,'--speed='+str(speed),'--out='+str(folder)]
        if actions:cmd+=['--actions='+str(actions)]
        if verify:cmd+=['--verify-pcm'] if engine=='legacy' else ['--capture='+str(capture)]
        row=run(name,cmd,1200);summary=folder/'summary.json';row['summary']=json.loads(summary.read_text()) if summary.exists() else None
        if row['summary'] is None:return row
        if verify:
            ref=data/(name+'_reference.f32');refInfo=data/(name+'_reference.json')
            if dynamic:
                prefix=data/(name+'_reference');r=run(name+'_oracle',[captured,source,round(speed*1e6),preset,folder/'session_1',ref,prefix],600)
                info=json.loads(refInfo.read_text()) if refInfo.exists() else None
            else:
                r=run(name+'_oracle',[reference,source,round(speed*1e6),preset,ref],600)
                log=Path(r['log']).read_text();info=json.loads(log) if r['exit']==0 else None
                if info:refInfo.write_text(json.dumps(info,indent=2)+'\n')
            if info:
                if engine=='progressive':exact=capture.is_file() and sha(capture)==info['pcm_sha256'] and capture.stat().st_size==ref.stat().st_size
                else:exact=row['summary']['sessions'][0]['published_pcm_sha256']==info['pcm_sha256'] and row['summary']['sessions'][0]['published_frames']==info['output_frames']
                if dynamic:exact&=(folder/'session_1/dynamic_map.nodes.bin').read_bytes()==Path(str(data/(name+'_reference'))+'.nodes.bin').read_bytes()
                row['pcm']={'PASS':exact,'scope':'callback受信raw全PCM' if engine=='progressive' else '公開済み生成raw全PCM（callback内容の直接捕捉ではない）','reference_sha256':info['pcm_sha256'],'reference_frames':info.get('output_frames',info.get('frames')),'actual_sha256':sha(capture) if engine=='progressive' else row['summary']['sessions'][0]['published_pcm_sha256'],'reference_binary_sha256':binaries[str(captured if dynamic else reference)]}
            else:row['pcm']={'PASS':False,'reason':'independent reference failed'}
        (output/(name+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
        (output/'driver.json').write_text(json.dumps(rows,indent=2)+'\n');return row
    if args.suite=='representative':
        run('release_adapter_api',[ROOT/'build/phase60_adapter_tests',ROOT/'results/phase31/input/mix.wav'],120)
        run('debug_adapter_api',[ROOT/'build/phase60/debug/phase60_adapter_tests',ROOT/'results/phase31/input/mix.wav'],150)
        source441=ROOT/'results/phase31/input/mix.wav';source48=data/'boundary_48000_f32.wav';fixture(source48,48000,2,3,'boundary',6)
        for source,label in ((source441,'44100'),(source48,'48000')):
            for preset in ('candidate','baseline'):
                for engine in ('legacy','progressive'):compare(label+'_'+preset+'_'+engine,source,engine,preset,verify=True)
        actions=data/'dynamic.csv';actions.write_text('at_s,action,value\n0.5,speed,0.41\n0.5,speed,2.00\n0.5,speed,0.49\n1.0,pause,0\n1.2,resume,0\n2.0,speed,0.50\n3.0,speed,2.00\n4.0,speed,1.00\n')
        for preset in ('candidate','baseline'):compare('dynamic_'+preset,source441,'progressive',preset,.40,actions,True,True)
        actions=data/'stop_play.csv';actions.write_text('at_s,action,value\n0.5,pause,0\n0.7,resume,0\n1.0,stop_play,0\n')
        for engine in ('progressive','legacy'):compare('stop_play_'+engine,source441,engine,actions=actions)
    else:
        source=Path(json.loads((ROOT/'results/phase60/INPUT.json').read_text())['wav'])
        # A/B then B/A, fresh processes. OS cache is observed, never called cold.
        for index,engine,verify in [(0,'legacy',False),(1,'progressive',False),(2,'progressive',True),(3,'legacy',True)]:
            compare(f'user_{index}_{engine}',source,engine,verify=verify)
    summary=summarize(rows,12 if args.suite=='representative' else 4,10 if args.suite=='representative' else 2)
    for path,expected in binaries.items():assert sha(path)==expected
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False),flush=True)
    return 0 if not summary['failures'] else 2
if __name__=='__main__':raise SystemExit(main())
