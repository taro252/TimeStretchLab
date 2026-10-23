"""callbackを止めず実部分混合中を観測。装置bufferはhostが必ず復元する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
from phase62_review_validation import verify
p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);record=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert record['status']=='PASS' and source['sha256']==record['source'];binary=record['binaries']['phase62_partial_mix_native'];assert identity(Path(binary['path']))==binary;input=ROOT/'results/phase31/input/mix.wav';jobs=[dict(id=mode+'_'+preset,binary='phase62_partial_mix_native',expected=1,command=[binary['path'],mode,str(input),preset,str(out/(mode+'_'+preset))]) for preset in ['baseline','candidate'] for mode in ['replace','clear','stop']]
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
save('EXPECTED.json',dict(expected_programs=6,expected_checks=6,source=source,build=identity(a.build_record),binary=binary,input=identity(input),jobs=jobs,driver=identity(Path(__file__)),serial=True,device_buffer_restoration_required=True));rows=[]
for j in jobs:
 start=time.monotonic();timed=False
 with (out/(j['id']+'.log')).open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 stat,reasons=verify(j,out/j['id'],code,timed)
 if not stat.get('buffer_restored'):reasons.append('device buffer restoration')
 if source_manifest(ROOT)!=source or identity(Path(binary['path']))!=binary:reasons.append('source/binary changed')
 rows.append(dict(id=j['id'],command=j['command'],status='PASS' if not reasons else 'FAIL',exit=code,timeout=timed,seconds=time.monotonic()-start,reasons=reasons,summary=stat));done=len(rows)==6;save('SUMMARY.json',dict(status='PASS' if done and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',run_complete=done,expected_programs=6,executed_programs=len(rows),expected_checks=6,executed_checks=sum(r['summary'].get('executed',0) for r in rows),rows=rows,RT_approval='NOT_ASSESSED'));print(j['id'],rows[-1]['status'],round(rows[-1]['seconds'],2),reasons,flush=True)
 if reasons:raise SystemExit(2)
