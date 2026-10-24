"""C2: 全解析前のExactと旧owner終了後の全suffix。通常worker gate、実機/性能承認ではない。"""
import argparse,itertools,json,pathlib,subprocess,sys,time,math,struct,hashlib
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=pathlib.Path,required=True)
p.add_argument('--references',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--worker',choices=['standard','workgroup'],default='standard');p.add_argument('--only',nargs='+');a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
build=json.loads(a.build_record.read_text());assert build['status']=='PASS' and source_manifest(R)['sha256']==build['source']
host=build['binaries']['performance_partial_analysis_tests'];assert identity(host['path'])==host
refs=json.loads((a.references/'SUMMARY.json').read_text());expected_refs=json.loads((a.references/'EXPECTED.json').read_text());provenance=json.loads((a.references/'REFERENCE_PROVENANCE.json').read_text())
assert refs['status']=='PASS' and refs['executed']==refs['expected']==12
assert identity(provenance['manifest']['path'])==provenance['manifest']
assert identity(provenance['binary']['path'])==provenance['binary']==expected_refs['reference']
assert provenance['binary']['sha256']=='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
index={r['id']:r for r in refs['rows']};specs={r['id']:r for r in expected_refs['jobs']};jobs=[]
for rate,ch,preset in itertools.product([48000,44100],[1],['candidate','baseline']):
 ch=1 if rate==48000 else 2
 for mode,speed in [(m,s) for m in ['same','changed'] for s in [400000,1000000,2000000]]+[(m,1000000) for m in ['cancel_seek','last_stop','unstarted_last','final_fast','final_loop','final_eos']]:
  key=f'{rate}_{ch}_{preset}_{mode}_{speed}';refkey=f'{rate}_{ch}_{speed}_{preset}';spec=specs[refkey]
  if a.only and key not in a.only:continue
  jobs.append(dict(id=key,reference_id=refkey,checks=8,suffix=mode in ['same','changed'],command=[host['path'],mode,spec['input']['path'],preset,str(speed),str(o/key),build['source'],*(['--worker=workgroup'] if a.worker=='workgroup' else [])]))
if a.only:assert {j['id'] for j in jobs}==set(a.only)
def save(n,v):(o/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
save('EXPECTED.json',dict(worker=a.worker,source=build['source'],host=host,build=identity(a.build_record),driver=identity(__file__),references=[identity(a.references/f) for f in ['EXPECTED.json','SUMMARY.json','REFERENCE_PROVENANCE.json']],expected_programs=len(jobs),expected_checks=len(jobs)*8,expected_suffix=sum(j['suffix'] for j in jobs),jobs=jobs,realtime_approval=False,performance_approval=False,callback_gate=False))
rows=[]
for j in jobs:
 start=time.monotonic();timed=False
 with (o/(j['id']+'.log')).open('w') as f:
  try:rc=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 path=o/j['id']/'SUMMARY.json';s=json.loads(path.read_text()) if path.exists() else {};reason=[];pcm=None
 ok=not timed and rc==0 and s.get('status')=='PASS' and s.get('run_complete') is True and s.get('expected')==s.get('executed')==8 and s.get('source')==build['source'] and s.get('binary_sha256')==host['sha256']
 if ok:
  obs=[json.loads(line) for line in (o/j['id']/'observations.jsonl').read_text().splitlines()];assert obs
  checks=[json.loads(line) for line in (o/j['id']/'checks.jsonl').read_text().splitlines()];spec_ids=json.loads((o/j['id']/'EXPECTED.json').read_text())['required_ids'];ok=len(checks)==8 and len({x['id'] for x in checks})==8 and {x['id'] for x in checks}==set(spec_ids) and all(x['status']=='PASS' for x in checks) and s.get('worker')==a.worker
 if ok and j['suffix']:
  ref=index[j['reference_id']];spec=specs[j['reference_id']];assert identity(ref['raw']['path'])==ref['raw'] and identity(spec['input']['path'])==spec['input']
  start_frame=ref['metadata']['positions'][1];end_frame=ref['metadata']['output_frames'];channels=ref['metadata']['channels'];raw=o/j['id']/'suffix.f32';actual=identity(raw)
  h=hashlib.sha256();equal=True;finite=True;count=0
  with open(ref['raw']['path'],'rb') as before,raw.open('rb') as after:
   before.seek(start_frame*channels*4)
   while block:=after.read(65536):
    equal&=block==before.read(len(block));finite&=len(block)%4==0 and all(math.isfinite(x[0]) for x in struct.iter_unpack('<f',block));h.update(block);count+=len(block)
   equal&=before.read(1)==b''
  ok=bool(equal and finite and count==(end_frame-start_frame)*channels*4 and s['output_start_frame']==start_frame and s['output_frames']==end_frame and s['suffix_frames']==end_frame-start_frame and s['suffix_sha256']==actual['sha256']==h.hexdigest() and s['prefix_PCM_before_final_frames']>0)
  pcm=dict(PASS=ok,all_bytes_equal=equal,finite=finite,bytes=count,actual=actual,reference=ref['raw'],reference_begin_frame=start_frame,reference_end_frame=end_frame)
  save(j['id']+'_PCM_AUDIT.json',pcm)
 rows.append(dict(id=j['id'],PASS=bool(ok),returncode=rc,timeout=timed,wall_s=time.monotonic()-start,summary=s,pcm=pcm));save('SUMMARY.json',dict(status='PASS' if len(rows)==len(jobs) and all(r['PASS'] for r in rows) else 'INCOMPLETE_OR_FAIL',run_complete=len(rows)==len(jobs),expected_programs=len(jobs),executed_programs=len(rows),expected_checks=len(jobs)*8,executed_checks=sum(r['summary'].get('executed',0) for r in rows),expected_suffix=sum(j['suffix'] for j in jobs),matched_suffix=sum(r['pcm'] is not None and r['pcm']['PASS'] for r in rows),rows=rows));print(j['id'],rc,ok,flush=True)
 if not ok:raise SystemExit(2)
assert source_manifest(R)['sha256']==build['source'] and identity(host['path'])==host
