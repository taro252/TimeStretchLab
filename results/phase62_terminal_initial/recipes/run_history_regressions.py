"""A1と直接影響する回帰。実音声を直列実行し、全IDと終了統計を検査する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase62_review_validation import verify
from phase62_finish_validation import verify_close_audit
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser(__doc__);p.add_argument('--build-record',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);a=p.parse_args()
 record=json.loads(a.build_record.read_text());assert record['status']=='PASS';source=source_manifest(ROOT);assert source['sha256']==record['source'];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);b=record['binaries'];jobs=[];mix=ROOT/'results/phase31/input/mix.wav';inputs=ROOT/'build/phase62_e5_review_20261021_01/inputs'
 def add(mode,binary,input,preset,expected,suffix=False):
  key=mode+'_'+preset;args=[b[binary]['path'],mode,str(input),preset,str(out/key)];args+= [source['sha256']] if suffix else [];jobs.append(dict(id=key,binary=binary,command=args,expected=expected))
 for preset in ['baseline','candidate']:
  for mode,n in [('terminal_immutability',14),('clear_continuation',8),('no_speed_clear',5)]:add(mode,'phase62_history_clear_native',a.fixture.resolve(),preset,n,True)
  for mode in ['initial_return_clear','initial_started_clear','committed_preparing','manual_seek','ready','started_no_pcm']:add(mode,'phase62_paused_clear_native',mix,preset,2)
  add('limit_close','phase62_playing_ledger_native',mix,preset,6)
  for mode,file,n in [('f01_dsp_done','short240ms.wav',7),('f01_checkpoint','one_second.wav',7),('f01_selected_clear','one_second.wav',6)]:add(mode,'phase62_adoption_review_native',inputs/file,preset,n,True)
 add('terminal_states','phase62_history_clear_native',a.fixture.resolve(),'baseline',7,True)
 jobs.append(dict(id='ledger_unit',binary='phase62_loop_speed_ledger_tests',command=[b['phase62_loop_speed_ledger_tests']['path']],expected=10))
 for j in jobs:assert identity(Path(b[j['binary']]['path']))==b[j['binary']]
 save(out/'EXPECTED.json',dict(source=source,build_record=identity(a.build_record),driver=identity(Path(__file__)),binaries=b,inputs=[identity(x) for x in [a.fixture.resolve(),mix,inputs/'short240ms.wav',inputs/'one_second.wav']],expected_programs=len(jobs),expected_checks=sum(j['expected'] for j in jobs),jobs=jobs,serial=True,RT_deadline_approval='NOT_ASSESSED'))
 rows=[]
 for j in jobs:
  assert source_manifest(ROOT)==source;start=time.monotonic();timed=False;log=out/(j['id']+'.log')
  with log.open('w') as f:
   try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
   except subprocess.TimeoutExpired:code=None;timed=True
  if j['id']=='ledger_unit':
   try:stat=json.loads(log.read_text());reasons=[] if code==0 and not timed and stat==dict(expected=10,executed=10,PASS=True,actual_admission_boundary=4096) else ['unit result']
   except (ValueError,OSError):stat={};reasons=['unit result absent']
  else:
   stat,reasons=verify(j,out/j['id'],code,timed)
   if j['id'].startswith('limit_close') and not verify_close_audit(out/j['id'],stat):reasons.append('close owned audit')
  assert source_manifest(ROOT)==source
  rows.append(dict(id=j['id'],status='FAIL' if reasons else 'PASS',exit=code,timeout=timed,expected=j['expected'],executed=stat.get('executed',0),seconds=time.monotonic()-start,reasons=reasons,log=identity(log),summary=stat))
  done=len(rows)==len(jobs);save(out/'SUMMARY.json',dict(status='PASS' if done and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',run_complete=done,source=source['sha256'],expected_programs=len(jobs),executed_programs=len(rows),expected_checks=sum(j['expected'] for j in jobs),executed_checks=sum(r['executed'] for r in rows),rows=rows,public_go=False,RT_deadline_approval='NOT_ASSESSED'))
  print(j['id'],rows[-1]['status'],round(rows[-1]['seconds'],2),reasons,flush=True)
 return 0 if all(r['status']=='PASS' for r in rows) else 2
if __name__=='__main__':raise SystemExit(main())
