"""Additional stage/resource statistics from completed paired startup records."""
import json,statistics,sys
from pathlib import Path
from phase57_study import ROOT
base=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'results/phase58/startup_final';out=base/'stage_resource_statistics.json';assert not out.exists()
rows=json.loads((base/'rows.json').read_text());result=[]
for seconds in (30,180,300):
 for preset in ('candidate','baseline'):
  group=[r for r in rows if r['seconds']==seconds and r['preset']==preset]
  for method in ('legacy','native'):
   for i,state in enumerate(('cold','restart')):
    data=[r[method][i] for r in group if r[method][i]]
    keys=('prepare_return_s','metadata_s','identity_s','analysis_s','map_s','prefill_s','analysis_cpu_s','published_worker_cycle_cpu_s','process_cpu_s','peak_rss_bytes') if method=='legacy' else ('verified_s','identified_s','analysis_start_s','first_event_s','first_map_s','first_generated_s','first_published_s','ready_s','play_requested_s','av_configured_s','audio_started_s','first_callback_s','analysis_done_s','analysis_cpu_s','analysis_worker_cpu_s','dsp_cpu_s','dsp_worker_cpu_s','process_cpu_s','peak_rss_bytes','reference_bytes','source_snapshot_bytes','snapshot_peak_bytes','non_eos_published','input_at_first_pcm','input_at_ready','fifo_high_water')
    record=dict(seconds=seconds,preset=preset,method=method,state=state,records=len(data),timing_valid=sum(bool(d['startup_timing_valid']) for d in data),statistics={})
    for key in keys:
     values=[d[key] for d in data if key in d and d[key] is not None and d[key]>=0 and (method!='native' or key not in ('analysis_cpu_s','snapshot_peak_bytes') or d['analysis_done'])]
     record['statistics'][key]=dict(n=len(values),median=statistics.median(values),max=max(values),population_stddev=statistics.pstdev(values)) if values else None
    result.append(record)
out.write_text(json.dumps(result,indent=2)+'\n');print('Startup stage/resource groups',len(result))
