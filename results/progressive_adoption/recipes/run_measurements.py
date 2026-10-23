"""Separate bounded native measurements, one executable at a time."""
import argparse,json,subprocess,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--build-record',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--only',nargs='+');p.add_argument('--suite',choices=['clock','ab','review','long'],required=True);a=p.parse_args();b=a.base;out=a.output;out.mkdir(parents=True,exist_ok=False);original=Path('/Users/taro252/Docker/TimeStretchLab');build=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert build['status']=='PASS' and source['sha256']==build['source'];jobs=[];resources=[]
def add(key,target,args,timeout,summary='SUMMARY.json'):
 binary=build['binaries'][target];assert identity(Path(binary['path']))==binary;jobs.append(dict(id=key,command=[binary['path'],*map(str,args)],timeout_s=timeout,summary=summary,binary=binary))
mono=b/'inputs/mono48_16s.wav'
if a.suite=='clock':
 inp=original/'build/phase61/native_inputs/boundary_48000_2.wav';refs=[original/f'build/phase61/native_final_verify_48000_2/500000_{x}.f32' for x in ('candidate','baseline')];resources=[inp,*refs]
 assert identity(inp)['sha256']=='ebb61d453dde2d99eef3731c8bf17bd65679541dc942d9a7bcc8a6bb3238cacd'
 assert all(identity(x)['sha256']=='a3c6384b6268371f6866057826fbb7a56e53cc03a05f64968edf448eec9b4d4d' for x in refs)
 add('old_stereo48_half','progressive_adoption_clock_native',[inp,out/'old_stereo48_half','--speed',500000,'--rate',48000,'--candidate-reference',refs[0],'--baseline-reference',refs[1],'--repeats',10],180)
elif a.suite=='ab':
 inp=original/'results/phase56/long/chain_300s.wav';resources=[inp]
 for pos in (30,270):
  for mode in ('fresh','prewarm'):
   key=f'A{pos}_{mode}';add(key,'progressive_adoption_ab_native',[inp,'candidate',pos,.1,1,mode,'Playing',0,out/key],130)
 for mode,state,c in [('early_on','Playing',0),('prewarm','Paused',0),('fresh','Playing',31)]:
  key=f'A30_{mode}_{state}_C{c}';add(key,'progressive_adoption_ab_native',[inp,'candidate',30,.1,1,mode,state,c,out/key],130)
elif a.suite=='review':
 resources=[mono]
 for preset in ('candidate','baseline'):
  for mode in ('a1_cancel','a1_started','a2_initial_supply','a2_checkpoint_supply','a2_clear_started','f01_dsp_done','f01_checkpoint'):
   key=mode+'_'+preset;fixture=mono if mode.startswith('a1_') else original/'build/phase62_e5_review_20261021_01/inputs'/('short240ms.wav' if mode in ('a2_initial_supply','f01_dsp_done') else 'one_second.wav');resources.append(fixture);add(key,'phase62_adoption_review_native',[mode,fixture,preset,out/key,source['sha256']],90)
else:
 inp=original/'results/phase55/long/boundary_1_2_44100_180/full.wav';ref=original/'build/phase59_fix_artifacts/phase_before/reference.f32';resources=[inp,ref]
 assert identity(inp)['sha256']=='e5a589ce9e3ea436c53aadda233c96a8246e7a58466718600c82b68b47dd05ac'
 assert identity(ref)['sha256']=='dabd620ef05dcd1e84a4488883cdd4f962902d42f784ae5fc7f6efbbad6107b8'
 requests=out/'no_speed_requests.csv';requests.write_text('output_frame,speed_micros\n');resources.append(requests)
 for preset in ('candidate','baseline'):
  add(preset,'phase59_native',[inp,2000000,preset,ref,3969000,identity(ref)['sha256'],out/preset,'normal',0,2,0,0,0,'--speed-requests='+str(requests),'--profile=block','--sample-thread=on','--worker=workgroup','--resident-input=on'],150,'summary.json')
if a.only:jobs=[j for j in jobs if j['id'] in a.only];assert {j['id'] for j in jobs}==set(a.only)
def save(n,v):(out/n).write_text(json.dumps(v,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
save('ENVIRONMENT.json',{name:subprocess.run(command,capture_output=True,text=True).stdout for name,command in {'macOS':['/usr/bin/sw_vers'],'hardware':['/usr/sbin/sysctl','hw.model','hw.memsize','hw.ncpu'],'audio':['/usr/sbin/system_profiler','SPAudioDataType'],'time':['/bin/date','-u'],'binary_arch':['/usr/bin/file',jobs[0]['binary']['path']]}.items()})
save('EXPECTED.json',dict(suite=a.suite,source=source,build=identity(a.build_record),driver=identity(Path(__file__)),expected_programs=len(jobs),resources=[identity(x) for x in resources],jobs=jobs,serial=True,ab_samples_per_condition=1 if a.suite=='ab' else None,physical_audio=None));rows=[]
for j in jobs:
 assert source_manifest(ROOT)==source;start=time.monotonic();timed=False
 with (out/(j['id']+'.log')).open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=j['timeout_s']).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 path=out/j['id']/j['summary'];s=json.loads(path.read_text()) if path.exists() else {};complete=not timed and bool(s) and (s.get('run_complete',s.get('execution_complete',True)))
 if a.suite=='ab':ok=complete and code==0 and s.get('functional') and s.get('rt_pass');perf=s.get('performance_pass') if s.get('performance_exercised') else 'NOT_EXERCISED'
 elif a.suite=='review':ok=complete and code==0 and s.get('status')=='PASS' and s.get('executed')==s.get('expected');perf='NOT_ASSESSED'
 else:ok=complete and code==0 and s.get('PASS') is True;perf='NOT_ASSESSED'
 rows.append(dict(id=j['id'],returncode=code,timeout=timed,wall_s=time.monotonic()-start,execution_complete=bool(complete),PASS=bool(ok),performance=perf,summary=s,log=identity(out/(j['id']+'.log'))));save('SUMMARY.json',dict(suite=a.suite,status='PASS' if len(rows)==len(jobs) and all(x['PASS'] for x in rows) else 'INCOMPLETE_OR_FAIL',expected_programs=len(jobs),executed_programs=len(rows),rows=rows,physical_audio=None));print(j['id'],code,ok,perf,flush=True)
assert source_manifest(ROOT)==source
