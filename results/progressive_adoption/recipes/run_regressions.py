"""Serial bounded affected regressions. Expectations saved before execution."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--build-record',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--only',nargs='+');a=p.parse_args();b=a.base;out=a.output;out.mkdir(parents=True,exist_ok=False)
build=json.loads(a.build_record.read_text());src=source_manifest(ROOT);assert build['status']=='PASS' and build['source']==src['sha256'];bins=build['binaries'];jobs=[]
def add(i,target,args,expected=None):
 assert identity(Path(bins[target]['path']))==bins[target];jobs.append(dict(id=i,command=[bins[target]['path'],*map(str,args)],expected_checks=expected,binary=bins[target]))
mono=b/'inputs/mono48_16s.wav';oracle=Path('/Users/taro252/Docker/TimeStretchLab/build/phase61/oracle_release_v1/phase61_frozen_reference')
for target in ('progressive_adoption_contract_tests','phase61_contract_tests','phase60_contract_tests','phase62_loop_speed_ledger_tests'):add(target,target,[])
add('pipeline_sync','phase61_pipeline_sync_tests',[mono,'--standard-only']);add('fast_seek_state','phase61_fast_seek_tests',[mono]);add('stopped_speed','paused_speed_pipeline_tests',[Path('/Users/taro252/Docker/TimeStretchLab/results/phase31/input/mix.wav')])
for fixture in ('mono48_16s','stereo441_16s'):
 inp=b/'inputs'/f'{fixture}.wav'
 for preset in ('candidate','baseline'):
  ref=b/'references_short_01'/f'{fixture}_{preset}.f32';meta=json.loads(ref.with_suffix('.log').read_text());v=meta['positions'];i=f'{fixture}_{preset}'
  add('initial_'+i,'phase62_initial_checkpoint_tests',[inp,preset,ref,*[v[k] for k in (0,1,2,3,2,4)]])
  add('prefix_'+i,'phase62_prefix_checkpoint_tests',[inp,preset,ref,oracle,*[v[k] for k in (7,8,9,10,11,1)],out/('prefix_'+i)],16)
for preset in ('candidate','baseline'):
 add('summary_'+preset,'phase62_control_summary_tests',[Path('/Users/taro252/Docker/TimeStretchLab/build/phase62_control_ab_20261022_01/inputs/artificial_10s.wav'),preset,out/('summary_'+preset)],24)
 add('limit_'+preset,'progressive_adoption_limit_native',[mono,preset,out/('limit_'+preset),src['sha256']],10)
for mode in ('dynamic','standard'):add('input_'+mode,'phase62_input_watch_tests',[Path('/Users/taro252/Docker/TimeStretchLab/build/phase62_control_ab_20261022_01/inputs/artificial_6s.wav'),out/('input_'+mode),mode],26)
if a.only:jobs=[j for j in jobs if j['id'] in a.only];assert {j['id'] for j in jobs}==set(a.only)
def save(n,v):(out/n).write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
save('EXPECTED.json',dict(source=src,build=identity(a.build_record),inputs=[identity(mono),identity(b/'inputs/stereo441_16s.wav')],references=json.loads((b/'references_short_01/REFERENCES.json').read_text()),extra_input_identities=[identity(Path('/Users/taro252/Docker/TimeStretchLab/results/phase31/input/mix.wav')),identity(Path('/Users/taro252/Docker/TimeStretchLab/build/phase62_control_ab_20261022_01/inputs/artificial_10s.wav')),identity(Path('/Users/taro252/Docker/TimeStretchLab/build/phase62_control_ab_20261022_01/inputs/artificial_6s.wav'))],serial=True,programs=len(jobs),jobs=jobs));rows=[]
for j in jobs:
 assert source_manifest(ROOT)==src;t=time.monotonic();timeout=False
 with (out/(j['id']+'.log')).open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=150).returncode
  except subprocess.TimeoutExpired:code=None;timeout=True
 summary_file=out/j['id']/'SUMMARY.json';s=json.loads(summary_file.read_text()) if summary_file.exists() else None
 ok=code==0 and not timeout
 if j['expected_checks'] and s:
  values=[s.get(k) for k in ('executed','passed','expected') if k in s]
  ok=ok and s.get('status')=='PASS' and values and all(v==j['expected_checks'] for v in values)
 elif j['expected_checks']:ok=False
 rows.append(dict(id=j['id'],returncode=code,timeout=timeout,wall_s=time.monotonic()-t,PASS=bool(ok),summary=s,log=identity(out/(j['id']+'.log'))));save('SUMMARY.json',dict(status='PASS' if len(rows)==len(jobs) and all(x['PASS'] for x in rows) else 'INCOMPLETE',expected_programs=len(jobs),executed_programs=len(rows),rows=rows));print(j['id'],code,ok,flush=True)
assert source_manifest(ROOT)==src
