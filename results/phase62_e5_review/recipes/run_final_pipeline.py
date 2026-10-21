"""最終sourceを固定し、部分混合、決定的、独立PCM、実機を直列実行する。"""
import json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
BASE=ROOT/'build/phase62_e5_review_20261021_01'
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 out=BASE/'final_pipeline';out.mkdir(exist_ok=False);source=source_manifest(ROOT);python=sys.executable
 commands=[
  ('partial',[python,ROOT/'scripts/phase62_review_validation.py','--suite','partial','--build',BASE/'candidate_build','--inputs',BASE/'inputs','--output',BASE/'partial_final_v3','--build-provenance',BASE/'BUILD_REVIEW_07.json']),
  ('equivalence',[python,ROOT/'results/phase62_e5_review/recipes/certify_final_review.py']),
  ('strict',[python,ROOT/'scripts/phase62_gate_runner.py','--root',ROOT,'--build-base',BASE/'strict_builds','--release-build',BASE/'candidate_build','--output',BASE/'strict_final']),
  ('offline',[python,ROOT/'results/phase62_finish/recipes/run_remaining_gates.py','--group','offline','--build-base',BASE/'runtime','--output',BASE/'offline_final']),
  ('native',[python,ROOT/'results/phase62_finish/recipes/run_remaining_gates.py','--group','native','--build-base',BASE/'runtime','--output',BASE/'native_final']),
 ]
 save(out/'EXPECTED.json',dict(source=source,expected=5,driver=identity(Path(__file__)),interpreter=identity(Path(python)),commands=[dict(id=k,argv=list(map(str,c))) for k,c in commands],serial=True))
 rows=[]
 for name,command in commands:
  assert source_manifest(ROOT)==source,'source changed before '+name
  log=out/(name+'.log');start=time.monotonic();timed=False
  with log.open('w') as stream:
   child=subprocess.Popen(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
   try:code=child.wait(timeout=14400)
   except subprocess.TimeoutExpired:
    timed=True;os.killpg(child.pid,signal.SIGTERM)
    try:child.wait(timeout=15)
    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    code=None
  passed=code==0 and not timed and source_manifest(ROOT)==source
  rows.append(dict(id=name,status='PASS' if passed else 'FAIL',exit=code,timed_out=timed,seconds=time.monotonic()-start,log=identity(log)))
  complete=len(rows)==5;save(out/'SUMMARY.json',dict(status='PASS' if complete and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',run_complete=complete,source_inventory_sha256=source['sha256'],expected=5,executed=len(rows),rows=rows,local_overall_go=False))
  print(name,rows[-1]['status'],round(rows[-1]['seconds'],2),flush=True)
  if not passed:return 2
 return 0
if __name__=='__main__':raise SystemExit(main())
