"""中間F01単発期限超過を隠さず、旧/最終binaryで同じ窓を少数比較する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity
from phase62_review_validation import verify
p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);jobs=[]
for name,path in [('A1_before_A2',a.before),('A2_final',a.after)]:
 record=json.loads(path.read_text());assert record['status']=='PASS';binary=record['binaries']['phase62_adoption_review_native'];assert identity(Path(binary['path']))==binary
 for trial in range(5):
  key=name+str(trial);jobs.append(dict(id=key,binary='phase62_adoption_review_native',expected=7,source=record['source'],command=[binary['path'],'f01_dsp_done',str(ROOT/'build/phase62_e5_review_20261021_01/inputs/short240ms.wav'),'candidate',str(out/key),record['source']]))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
save(out/'EXPECTED.json',dict(expected_programs=10,expected_checks=70,before=identity(a.before),after=identity(a.after),jobs=jobs,serial=True,original_failure_preserved=True,thresholds_unchanged=True,RT_approval='NOT_ASSESSED'));rows=[]
for j in jobs:
 start=time.monotonic();log=out/(j['id']+'.log');timed=False
 with log.open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 stat,reasons=verify(j,out/j['id'],code,timed);rows.append(dict(id=j['id'],status='PASS' if not reasons else 'FAIL',exit=code,timeout=timed,seconds=time.monotonic()-start,reasons=reasons,summary=stat,log=identity(log)))
 save(out/'SUMMARY.json',dict(status='PASS' if len(rows)==10 and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',run_complete=len(rows)==10,expected_programs=10,executed_programs=len(rows),expected_checks=70,executed_checks=sum(x['summary'].get('executed',0) for x in rows),rows=rows,original_deadline_failure_not_reclassified=True,RT_approval='NOT_ASSESSED'));print(j['id'],rows[-1]['status'],flush=True)
raise SystemExit(0 if all(x['status']=='PASS' for x in rows) else 2)
