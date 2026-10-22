"""実装前固定目標だけで性能の最終判定を行う。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert not a.output.exists();before=json.loads(a.before.read_text());after=json.loads(a.after.read_text());assert before['status']==after['status']=='PASS' and before['run_complete'] and after['run_complete'] and before['executed_programs']==after['executed_programs']==7 and before['executed_samples']==after['executed_samples']==14;rows=[]
for old,new in zip(before['aggregates'],after['aggregates']):
 assert (old['A_seconds'],old['cache'])==(new['A_seconds'],new['cache']);warm=new['cache']=='same_prepare_re_request' and new['A_seconds']>0
 threshold=min(1.,old['median_s']*.2) if warm else old['median_s']+.25 if new['A_seconds']==0 else old['median_s']*1.2+.25
 rows.append(dict(A=new['A_seconds'],condition=new['cache'],before=old,after=new,maximum_median_s=threshold,reduction_percent=100*(1-new['median_s']/old['median_s']),PASS=new['n']==old['n']==2 and new['median_s']<=threshold))
for r in after['rows']:
 assert len(r['samples'])==2
 for index,sample in enumerate(r['samples']):
  assert sample['missing']==sample['callback_new']==0 and sample['device_rate']==48000 and sample['device_buffer']==512 and sample['checkpoint_peak']<=2
  if index and sample['output_start']>0:assert sample['checkpoint_start']>0 and sample['checkpoint_start']+sample['cold_discarded_frames']==sample['output_start'] and sample['cold_discarded_frames']<2048
r=dict(status='PASS' if all(x['PASS'] for x in rows) else 'FAIL',run_complete=True,expected=6,executed=6,rows=rows,acceptance=identity(a.plan),before=identity(a.before),after=identity(a.after),driver=identity(Path(__file__)),host_difference='mainを省くpreprocessor guardだけ。測定関数・条件・時計・30ms静止確認は同じ',early_actual_flags=[s['final_analysis_before_request'] for group in [before,after] for row in group['rows'] if row['id']=='A0_early_trial0' for s in row['samples']],physical_time='NOT_MEASURED',p95='NOT_ESTIMATED',public_go=False)
a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['status']);raise SystemExit(0 if r['status']=='PASS' else 2)
