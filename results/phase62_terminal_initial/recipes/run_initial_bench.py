"""同一入力/host条件で初回ABと同prepare再要求を直列測定。旧結果は上書きしない。"""
import argparse,json,subprocess,sys,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser(__doc__);p.add_argument('--build-record',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);record=json.loads(a.build_record.read_text());assert record['status']=='PASS';binary=Path(record['binaries']['phase62_initial_loop_native']['path']);source=record.get('source',record.get('source_inventory_sha256'));assert identity(binary)==record['binaries'][binary.name]
 jobs=[]
 for start in [0,30,270]:
  for trial in [0,1]:
   key=f'A{start}_final_trial{trial}';jobs.append(dict(id=key,A_seconds=start,trial=trial,analysis_policy='final',command=list(map(str,[binary,a.input.resolve(),'baseline',start,2,2,'final',0,1,out/key]))))
 jobs.append(dict(id='A0_early_trial0',A_seconds=0,trial=0,analysis_policy='early',command=list(map(str,[binary,a.input.resolve(),'baseline',0,2,2,'early',0,1,out/'A0_early_trial0']))))
 save(out/'EXPECTED.json',dict(source=source,root_source=source_manifest(ROOT)['sha256'],input=identity(a.input),build_record=identity(a.build_record),binary=identity(binary),driver=identity(Path(__file__)),expected_programs=7,expected_samples=14,required_ids=[j['id'] for j in jobs],jobs=jobs,serial_audio=True,physical_audio_time='NOT_MEASURED',percentile95='NOT_ESTIMATED'))
 rows=[]
 for j in jobs:
  start=time.monotonic();timed=False
  with (out/(j['id']+'.log')).open('w') as log:
   try:code=subprocess.run(j['command'],stdout=log,stderr=subprocess.STDOUT,timeout=360).returncode
   except subprocess.TimeoutExpired:code=None;timed=True
  folder=out/j['id'];spec=json.loads((folder/'EXPECTED.json').read_text()) if (folder/'EXPECTED.json').exists() else {};result=json.loads((folder/'SUMMARY.json').read_text()) if (folder/'SUMMARY.json').exists() else {};samples=[json.loads(l) for l in (folder/'measurements.jsonl').read_text().splitlines()] if (folder/'measurements.jsonl').exists() else []
  ok=code==0 and not timed and result.get('status')=='PASS' and result.get('run_complete') is True and spec.get('expected')==result.get('expected')==result.get('executed')==len(samples)==2 and [r['round'] for r in samples]==[0,1]
  rows.append(dict(id=j['id'],status='PASS' if ok else 'INCOMPLETE' if timed else 'FAIL',exit=code,timed_out=timed,seconds=time.monotonic()-start,samples=samples,summary=result,log=identity(out/(j['id']+'.log'))))
  done=len(rows)==len(jobs);aggregates=[]
  for at in [0,30,270]:
   for round_index in [0,1]:
    values=[s['accepted_to_A_alignment_s']+s['Ready_observed_to_first_A_PCM_s'] for r in rows if r['id'].startswith(f'A{at}_final_') and r['status']=='PASS' for s in r['samples'] if s['round']==round_index]
    if values:aggregates.append(dict(A_seconds=at,cache='same_prepare_re_request' if round_index else 'fresh_prepare',n=len(values),values_s=values,min_s=min(values),max_s=max(values),median_s=statistics.median(values)))
  save(out/'SUMMARY.json',dict(status='PASS' if done and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',run_complete=done,source=source,expected_programs=7,executed_programs=len(rows),expected_samples=14,executed_samples=sum(len(r['samples']) for r in rows),rows=rows,aggregates=aggregates,RT_deadline_approval='NOT_ASSESSED',public_go=False))
  print(j['id'],rows[-1]['status'],round(rows[-1]['seconds'],2),flush=True)
  if not ok:return 2
 return 0
if __name__=='__main__':raise SystemExit(main())
