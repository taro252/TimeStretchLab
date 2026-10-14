"""Read-only aggregate of saved trials, with explicit correction provenance."""
import csv,json,math,statistics,hashlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase52'
def distribution(v):
 return dict(count=len(v),median=statistics.median(v) if v else None,p95=sorted(v)[max(0,math.ceil(.95*len(v))-1)] if v else None,max=max(v,default=None))
rows=[]
for run in sorted((OUT/'native').iterdir()):
 path=next((run/name for name in ('summary_round_eos.json','summary_samples.json','summary.json') if (run/name).exists()),None)
 if not path:continue
 for row in json.loads(path.read_text()):
  row=dict(row);case=ROOT/row['case'];workers=list(csv.DictReader((case/'workers.csv').open()));interval=[]
  for i,w in enumerate(workers):
   value=float(w['publication_interval_s']);assert math.isfinite(value)
   if value==-1 and i==0:continue
   assert value>=0;interval.append(value*1000)
  row['publication_interval_ms']=distribution(interval)
  row['worker_cycle_wall_ms']=distribution([float(w['wall_s'])*1000 for w in workers])
  row['worker_cycle_cpu_ms']=distribution([float(w['cpu_s'])*1000 for w in workers])
  row['cpu_percent_process']=float(row['cpu_seconds'])*100/float(row['playback_wall_s'])
  row['rss_mib']=float(row['max_rss'])/1024**2
  callbacks=list(csv.DictReader((case/'callbacks.csv').open()));cursor=presented=0;valid=True
  for c in callbacks:
   if int(c['wanted']):valid&=int(c['output'])==cursor
   cursor+=int(c['received']);presented+=int(c['wanted'])
  row['callback_pcm_continuity']=valid and cursor==int(row['consumed_frames']) and presented==int(row['presented_frames'])
  row['callback_fifo_min']=min((int(c['fifo_before']) for c in callbacks if int(c['wanted'])),default=None)
  rows.append(row)
ordinary=[r for r in rows if not r.get('intentional_stall')]
valid=[r for r in ordinary if r['VERDICT']=='PASS']
faults=[r for r in rows if r.get('intentional_stall')]
summary=dict(total=len(rows),ordinary=len(ordinary),pass_count=len(valid),fail_or_unmeasured=len(ordinary)-len(valid),intentional_faults=[dict(case=r['case'],missing=r['missing_frames'],max_continuous=r['max_continuous_missing'],detection=r.get('FAULT_DETECTION'),audio=r['AUDIO_QUALITY']) for r in faults],valid_pcm_continuity=all(r['callback_pcm_continuity'] for r in valid),host_errors=sum(int(r[k]) for r in valid for k in ('host_missing','host_backwards','host_cadence_errors','sample_errors','hal_window_misses')),missing_sum=sum(int(r['missing_frames']) for r in valid),callback_max_us=max(float(r['callback_max_ns'])/1000 for r in valid),rss_mib=distribution([r['rss_mib'] for r in valid]),cpu_percent=distribution([r['cpu_percent_process'] for r in valid]),ordinary_failures=[r['case'] for r in ordinary if r['VERDICT']!='PASS'])
(OUT/'native_aggregate.json').write_text(json.dumps(dict(summary=summary,rows=rows),indent=2))
print(json.dumps(summary,indent=2))
