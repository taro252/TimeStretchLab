"""事前固定された30秒×3 median>=5%改善を判定。native-only、統計的因果は主張しない。"""
import argparse,json,statistics,sys,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert not a.output.exists()
def read(p):return json.loads(p.read_text())
plan=read(a.plan);assert plan['status']=='FROZEN_BEFORE_CANDIDATE_MEASUREMENT' and identity(a.baseline/'SUMMARY.json')==plan['baseline'] and plan['cpu']['n']==3
be,ce=read(a.baseline/'EXPECTED.json'),read(a.candidate/'EXPECTED.json');assert be['input']==ce['input'] and be['UI_included']==ce['UI_included']==False
for folder in (a.baseline,a.candidate):
 h=read(folder/'plain/EXPECTED.json');assert h['window_s']==30 and h['observer_hz']==5 and h['costs']==0
record_b=read(Path(be['build_record']['path']));record_c=read(Path(ce['build_record']['path']));assert record_b['configuration']==record_c['configuration']=='Release' and record_b['architecture']==record_c['architecture']=='arm64'
def host_sha(record):return next(f['sha256'] for f in record['source_manifest']['files'] if f['path']=='tests/Phase62ControlCpuNative.cpp')
assert host_sha(record_b)==host_sha(record_c)
b,c=read(a.baseline/'SUMMARY.json'),read(a.candidate/'SUMMARY.json');assert b['status']==c['status']=='PASS' and b['run_complete'] and c['run_complete'];rows=[]
def windows(s,stage):
 rows=[r for r in s['rows'] if r['id']==stage];assert len(rows)==1
 r=rows[0];ids=['unprepared','off1','off2','off3','loop2s','loop30s','paused','stopped'] if stage=='plain' else ['off1','paused'];assert r['status']=='PASS' and r['exit']==0 and not r['timeout'] and r['summary']['run_complete'] and r['summary']['expected']==r['summary']['executed']==len(ids) and [x['id'] for x in r['measurements']]==ids
 for w in r['measurements']:
  assert all(math.isfinite(w[k]) for k in ['cpu_s','wall_s','cpu_percent']) and w['wall_s']>0 and math.isclose(w['cpu_percent'],100*w['cpu_s']/w['wall_s'],rel_tol=1e-12)
  if w['id'] not in ('unprepared','stopped'):assert bool(w['before']['costs_measured'])==bool(w['after']['costs_measured'])==(stage=='attribution')
 return {x['id']:x for x in r['measurements']}
bw,cw=windows(b,'plain'),windows(c,'plain');assert bw.keys()==cw.keys()
for key in bw:
 x,y=bw[key],cw[key];assert x['device_rate']==y['device_rate'] and x['device_buffer']==y['device_buffer'];rows.append(dict(id=key,baseline_cpu_percent=x['cpu_percent'],candidate_cpu_percent=y['cpu_percent'],relative_reduction_percent=100*(1-y['cpu_percent']/x['cpu_percent']),baseline_wakeups_per_s=x['interrupt_wakeups']/x['wall_s'],candidate_wakeups_per_s=y['interrupt_wakeups']/y['wall_s'],baseline_rss_bytes=x['after']['rss'],candidate_rss_bytes=y['after']['rss'],baseline_deadline_delta=x['after']['deadlines']-x['before']['deadlines'],candidate_deadline_delta=y['after']['deadlines']-y['before']['deadlines']))
bmed=statistics.median(bw[k]['cpu_percent'] for k in ['off1','off2','off3']);cmed=statistics.median(cw[k]['cpu_percent'] for k in ['off1','off2','off3']);assert bmed==plan['cpu']['AB_OFF_before_median'] and plan['cpu']['maximum_candidate_median']==.95*bmed
for window_set in (bw,cw):
 for k in ['off1','off2','off3']:
  w=window_set[k];assert w['wall_s']>=30 and abs(w['polls']/w['wall_s']-5)<=.2
at=[]
for key in ['off1','paused']:
 x,y=windows(b,'attribution')[key],windows(c,'attribution')[key];costs={}
 for name in ['input_validation','speed_copy','monitor','sync']:
  costs[name]={}
  for label,w in [('baseline',x),('candidate',y)]:
   before,after=w['before'][name],w['after'][name];costs[name][label]=dict(calls_per_s=(after['calls']-before['calls'])/w['wall_s'],object_bytes=after['object_bytes']-before['object_bytes'],cpu_s=after['cpu_s']-before['cpu_s'],wall_s=after['wall_s']-before['wall_s'])
 assert y['after']['speed_copy']['calls']-y['before']['speed_copy']['calls']==plan['control']['empty_sync_full_history_copies'] and y['after']['seek_wakes']==y['before']['seek_wakes']
 at.append(dict(id=key,inclusive_costs=costs,baseline_seek_wakes=x['after']['seek_wakes']-x['before']['seek_wakes'],candidate_seek_wakes=y['after']['seek_wakes']-y['before']['seek_wakes'],baseline_analysis_wakes=x['after']['analysis_wakes']-x['before']['analysis_wakes'],candidate_analysis_wakes=y['after']['analysis_wakes']-y['before']['analysis_wakes']))
r=dict(status='PASS' if cmed<=.95*bmed else 'NOT_DEMONSTRATED',scope='native_only_no_UI',threshold='candidate median<=0.95*baseline median, 30seconds*3',baseline_median_cpu_percent=bmed,candidate_median_cpu_percent=cmed,relative_reduction_percent=100*(1-cmed/bmed),rows=rows,attribution=at,plan=identity(a.plan),baseline=identity(a.baseline/'SUMMARY.json'),candidate=identity(a.candidate/'SUMMARY.json'),limitations=['serial observational n=3, no randomization/confidence interval','same input/preset/device/5Hz getters; no Swift/UI/JSON','inclusive costs overlap; do not add them','RT deadline approval NOT_ASSESSED']);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:r[k] for k in ['status','baseline_median_cpu_percent','candidate_median_cpu_percent','relative_reduction_percent']},indent=2))
