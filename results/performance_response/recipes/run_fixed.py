"""固定全速度の独立RAWとstage digest ON/OFF。音声装置/RT承認は含まない。"""
import argparse,itertools,json,math,pathlib,struct,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase57_study import fixture
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=pathlib.Path,required=True)
p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--speeds',nargs='+',type=int,default=list(range(400000,2000001,10000)))
p.add_argument('--product-only',action='store_true');a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
build=json.loads(a.build_record.read_text());assert build['status']=='PASS' and source_manifest(R)['sha256']==build['source']
host=build['binaries']['phase58_check'];assert identity(host['path'])==host
oracle=R/'build/phase61/oracle_release_v1/phase61_frozen_reference';oracle_id=identity(oracle)
assert oracle_id['sha256']=='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
formats=list(itertools.product((44100,48000),(1,2),(3,) if a.product_only else (1,3)))
(o/'inputs').mkdir();inputs=[]
for rate,channels,encoding in formats:
 f=o/'inputs'/f'{rate}_{channels}_{encoding}.wav';fixture(f,rate,channels,encoding,'boundary',.25);inputs.append(dict(rate=rate,channels=channels,encoding=encoding,file=identity(f)))
def save(n,v):(o/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
groups=len(inputs)*len(a.speeds)*2;expected=groups*4
save('EXPECTED.json',dict(source=build['source'],build=identity(a.build_record),host=host,oracle=oracle_id,driver=identity(__file__),fixture_generator=identity(R/'scripts/phase57_study.py'),inputs=inputs,speeds=a.speeds,presets=['candidate','baseline'],chunks=[1024,5003],stage_digest_settings=['on','off'],expected_reference_groups=groups,expected_pcm_checks=expected,exact=True,realtime=False))
passed=failed=done_groups=0;start=time.monotonic()
def summary(complete):save('SUMMARY.json',dict(status='PASS' if complete and not failed and passed==expected else 'INCOMPLETE_OR_FAIL',run_complete=complete,expected_reference_groups=groups,completed_reference_groups=done_groups,expected_pcm_checks=expected,passed=passed,failed=failed,wall_s=time.monotonic()-start))
with (o/'rows.jsonl').open('x') as rows:
 for source,speed,preset in itertools.product(inputs,a.speeds,['candidate','baseline']):
  name=f"{source['rate']}_{source['channels']}_{source['encoding']}_{speed}_{preset}";folder=o/name;folder.mkdir();raw=folder/'reference.f32'
  cmd=[str(oracle),source['file']['path'],str(speed),preset,str(raw),'0'];r=subprocess.run(cmd,capture_output=True,text=True,timeout=90);(folder/'reference.log').write_text(r.stdout+r.stderr)
  if r.returncode:failed+=1;summary(False);raise RuntimeError('Frozen render failed: '+name)
  ref=json.loads(r.stdout);raw_id=identity(raw)
  assert raw_id['sha256']==ref['sha256'] and raw_id['bytes']==ref['output_frames']*source['channels']*4
  with raw.open('rb') as f:
   for chunk in iter(lambda:f.read(65536),b''):assert all(math.isfinite(x[0]) for x in struct.iter_unpack('<f',chunk))
  for chunk,digests in itertools.product((1024,5003),('on','off')):
   cmd=[host['path'],source['file']['path'],str(speed),preset,str(raw),str(ref['output_frames']),ref['sha256'],str(chunk),'--worker=workgroup','--resident-input=on','--stage-digests='+digests]
   r=subprocess.run(cmd,capture_output=True,text=True,timeout=90);log=folder/f'{chunk}_{digests}.log';log.write_text(r.stdout+r.stderr)
   actual=json.loads(r.stdout) if r.returncode==0 else {};ok=r.returncode==0 and actual.get('PASS') is True and actual.get('stage_digests_measured') is (digests=='on')
   rows.write(json.dumps(dict(id=name+f'_{chunk}_{digests}',PASS=ok,command=cmd,returncode=r.returncode,log=identity(log),reference=raw_id,result=actual),allow_nan=False)+'\n');rows.flush();passed+=ok;failed+=not ok
   if not ok:summary(False);raise RuntimeError('Fixed PCM/digest failure: '+name)
  done_groups+=1;summary(done_groups==groups)
  if done_groups%32==0:print(done_groups,'/',groups,'reference groups',passed,'PCM PASS',flush=True)
assert identity(oracle)==oracle_id and identity(host['path'])==host and source_manifest(R)['sha256']==build['source']
