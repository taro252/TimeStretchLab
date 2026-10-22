"""凍結Exact参照を独立生成し、初回warm復元と境界を直列検査する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase59_native_validation import wav_info
FIXED=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';FIXED_SHA='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--references-from',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);record=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert record['status']=='PASS' and record['source']==source['sha256'];assert identity(FIXED)['sha256']==FIXED_SHA;b=record['binaries'];base=ROOT/'build/phase62_terminal_initial_20261022_01';mono=base/'inputs/artificial_48000_mono_6s.wav';mix=ROOT/'results/phase31/input/mix.wav';long=ROOT/'build/phase62_fix/run_01/final_v9/evidence/release_longA/same_300s_48000_2_pcm16.wav';jobs=[]
 cases=[('mono_short125',mono,'baseline',.5,.1,1250000,'raw','paused'),('mono_uncached',mono,'baseline',.5,2.1,1000000,'uncached','paused'),('float_uncached040',mix,'candidate',.5,1,400000,'uncached','paused'),('float_short200',mix,'candidate',.5,.1,2000000,'raw','paused'),('mono_entry125_baseline',mono,'baseline',.5,.1,1250000,'raw','playing'),('mono_entry125_candidate',mono,'candidate',.5,.1,1250000,'raw','playing'),('longA270',long,'baseline',270,2,1000000,'raw','paused')]
 groups={}
 for key,input,preset,A,duration,speed,cache,mode in cases:
  rate=wav_info(input)['rate'];af=round(A*rate);bf=af+round(duration*rate);g=(str(input),preset,speed);group=groups.setdefault(g,dict(id=f'ref{len(groups)}',input=input,preset=preset,speed=speed,positions=[]));idx=len(group['positions']);group['positions'] += [af,bf]
  binary='phase62_initial_entry_native' if mode=='playing' else 'phase62_initial_loop_native';cmd=[b[binary]['path'],str(input),preset,str(A),str(duration)];cmd+= [str(speed/1e6),str(out/key)] if mode=='playing' else ['2','final','3',str(speed/1e6),str(out/key)]
  jobs.append(dict(id=key,input=str(input),preset=preset,speed=speed,cache=cache,mode=mode,ref=group['id'],indices=[idx,idx+1],command=cmd,binary=binary))
 # Independent RAW/map for the offline roundtrip, both presets. Same RAW may serve several A/Bs.
 for preset in ['baseline','candidate']:
  g=(str(mono),preset,1000000);group=groups.setdefault(g,dict(id=f'ref{len(groups)}',input=mono,preset=preset,speed=1000000,positions=[]));idx=len(group['positions']);group['positions'] += [0,4800,48017,52817,48017,192018];jobs.append(dict(id='offline_'+preset,mode='offline',preset=preset,ref=group['id'],indices=list(range(idx,idx+6)),binary='phase62_initial_checkpoint_tests',input=str(mono)))
 for j in jobs:assert identity(Path(b[j['binary']]['path']))==b[j['binary']]
 save(out/'EXPECTED.json',dict(source=source,build_record=identity(a.build_record),driver=identity(Path(__file__)),validator=identity(Path(__file__).with_name('validate_initial_pcm.py')),reference_binary=identity(FIXED),inputs=[identity(x) for x in [mono,mix,long]],jobs=jobs,reference_groups=list(groups.values()),expected_programs=9,expected_native_rounds=14,expected_reference_programs=0 if a.references_from else len(groups),reused_reference_directory=str(a.references_from.resolve()) if a.references_from else None,offline_expected_named_cases=14,serial=True,RT_deadline_approval='NOT_ASSESSED'))
 refs={};rows=[]
 def run(cmd,label,timeout=360):
  timed=False;start=time.monotonic();log=out/(label+'.log')
  with log.open('w') as f:
   try:code=subprocess.run(list(map(str,cmd)),stdout=f,stderr=subprocess.STDOUT,timeout=timeout).returncode
   except subprocess.TimeoutExpired:code=None;timed=True
  return dict(command=list(map(str,cmd)),exit=code,timeout=timed,seconds=time.monotonic()-start,log=identity(log))
 for g in groups.values():
  if a.references_from:
   oldspec=json.loads((a.references_from/'EXPECTED.json').read_text());oldgroup=next(x for x in oldspec['reference_groups'] if x['id']==g['id']);assert oldgroup==json.loads(json.dumps(g,default=str));assert oldspec['reference_binary']==identity(FIXED);assert oldspec['inputs']==[identity(x) for x in [mono,mix,long]]
   original=json.loads((a.references_from/'REFERENCES.json').read_text())[g['id']];assert original['exit']==0 and not original['timeout'];assert identity(Path(original['raw']['path']))==original['raw'];assert identity(Path(original['log']['path']))==original['log'];assert original['meta']['sha256']==original['raw']['sha256'];r=dict(original,reused_reference=True,source_record=identity(a.references_from/'REFERENCES.json'))
  else:
   raw=out/(g['id']+'.f32');cmd=[FIXED,g['input'],g['speed'],g['preset'],raw,*g['positions']];r=run(cmd,g['id']);assert r['exit']==0 and not r['timeout'];meta=json.loads(Path(r['log']['path']).read_text());assert identity(raw)['sha256']==meta['sha256'];r.update(raw=identity(raw),meta=meta)
  refs[g['id']]=r;save(out/'REFERENCES.json',refs)
 for j in jobs:
  assert source_manifest(ROOT)==source;ref=refs[j['ref']];meta=dict(ref['meta']);meta['positions']=[meta['positions'][i] for i in j['indices']];mapfile=out/(j['id']+'_map.json');save(mapfile,meta)
  if j['mode']=='offline':
   cmd=[b[j['binary']]['path'],j['input'],j['preset'],ref['raw']['path'],*meta['positions']];r=run(cmd,j['id']);lines=Path(r['log']['path']).read_text().splitlines();data=[json.loads(x) for x in lines];last=data[-1] if data else {};cases=[x for x in data if x.get('status')=='PASS' and 'case' in x];ok=r['exit']==0 and not r['timeout'] and last.get('status')=='PASS' and last.get('independent_fixed_raw_supplied')==1 and len(cases)==14 and last.get('owner_peak')<=2 and last.get('owner_alive')==0;r.update(expected=14,executed=len(cases))
  else:
   r=run(j['command'],j['id']);ok=r['exit']==0 and not r['timeout']
   if ok:
    cmd=[sys.executable,'-B',Path(__file__).with_name('validate_initial_pcm.py'),'--capture',out/j['id'],'--input',j['input'],'--host-binary',b[j['binary']]['path'],'--reference-binary',FIXED,'--reference-raw',ref['raw']['path'],'--reference-map',mapfile,'--preset',j['preset'],'--speed-micros',j['speed'],'--expected-rounds',2,'--min-cycles',3,'--require-cache-hit','--expected-cache-mode',j['cache'],'--case-id',j['id'],'--output',out/(j['id']+'_audit')]
    if j['mode']=='playing':cmd+=['--allow-playing-entry']
    validation=run(cmd,j['id']+'_validator');r['validation']=validation;ok=validation['exit']==0 and not validation['timeout']
    stat=json.loads((out/(j['id']+'_audit/SUMMARY.json')).read_text());r['audit_summary']=stat;r.update(expected=stat['expected'],executed=stat['passed']);ok &= stat['status']=='PASS' and stat.get('run_complete') is True and stat['expected']==stat['executed']==stat['passed']
  r.update(id=j['id'],status='PASS' if ok else 'FAIL');rows.append(r);done=len(rows)==len(jobs);save(out/'SUMMARY.json',dict(status='PASS' if done and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',run_complete=done,source=source['sha256'],expected_programs=9,executed_programs=len(rows),expected_native_rounds=14,expected_checks=70,executed_checks=sum(x.get('executed',0) for x in rows),reference_programs=0 if a.references_from else len(refs),reused_references=len(refs) if a.references_from else 0,rows=rows,RT_deadline_approval='NOT_ASSESSED'));print(j['id'],r['status'],r.get('executed'),flush=True)
 return 0 if all(x['status']=='PASS' for x in rows) else 2
if __name__=='__main__':raise SystemExit(main())
