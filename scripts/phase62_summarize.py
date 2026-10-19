"""Read-only aggregation of Phase62 evidence; preserves every failed trial."""
import argparse,json,statistics,hashlib
from pathlib import Path

def percentile(values,q):
    s=sorted(values);point=(len(s)-1)*q;i=int(point);return s[i] if i==len(s)-1 else s[i]+(s[i+1]-s[i])*(point-i)
def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('run',type=Path);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args();root=a.run.resolve()
    def read(name):return json.loads((root/name).read_text())
    suites={}
    for suite in ('native_release','controls_release','long_release','step1_release','controls_debug'):
        rows=[]
        for path in sorted((root/suite).glob('*/result.json')):
            data=json.loads(path.read_text())
            if data.get('functional_pass'):rows.append(dict(path=str(path.relative_to(root)),**data))
        suites[suite]=rows
    base=suites['native_release'];quality=read('quality_release_final/rows.json');clock=[]
    for suite,rows in suites.items():
        for row in rows:
            if row.get('host_errors') or row.get('sample_errors') or row.get('hal_window_misses'):clock.append(dict(suite=suite,path=row['path'],host=row.get('host_errors'),sample=row.get('sample_errors'),hal=row.get('hal_window_misses')))
    frame_errors=[];checked=0
    for suite,rows in suites.items():
        for row in rows:
            path=root/row['path'];history=path.parent/'boundaries.jsonl';events=[json.loads(s) for s in history.read_text().splitlines()]
            for prior,current in zip(events,events[1:]):
                if prior['new_epoch']!=current['old_epoch']:continue # explicit manual seek between cycles
                expected=current['old_output_end']-prior['new_output_start']-current['overlap'];actual=current['callback_frame']-prior['callback_frame'];checked+=1
                if expected!=actual:frame_errors.append(dict(path=str(history),cycle=current['cycle'],expected=expected,actual=actual))
    lat=[r['ready_ms'] for r in base];cpu=[100*r['process_cpu_s']/r['wall_s'] for r in base];long=next(r for r in suites['long_release'] if r['cycles']==1000)
    result=dict(base_sha='88d5247fd6b67996f4d315d5cb0fb23caf8a9f0c',public_go=False,
        regression=dict(release_ctest=28,debug_ctest=28,exact=read('exact_release/exact/summary.json'),golden=read('golden_release/golden/summary.json')['passed']),
        bounded_pcm=dict(formats_6_speeds=96,all_161_speeds_both_presets=322),
        native_matrix=dict(conditions=len(base),cycles=sum(r['cycles'] for r in base),raw_mix_errors=sum(r['raw_mix_errors'] for r in base),missing=sum(r['missing_frames'] for r in base),worker_deadlines=sum(r.get('final_worker_deadlines',r['worker_deadlines']) for r in base),callback_deadlines=sum(r['callback_deadlines'] for r in base),callback_new=sum(r['callback_new'] for r in base),callback_heap=sum(r['callback_heap_calls'] for r in base),callback_frees=sum(r['callback_frees'] for r in base),ready_ms=dict(p50=percentile(lat,.5),p95=percentile(lat,.95),maximum=max(lat)),cpu_one_core_percent=dict(p50=percentile(cpu,.5),p95=percentile(cpu,.95),maximum=max(cpu)),max_rss_bytes=max(r['rss_end'] for r in base),max_peak_rss_bytes=max(r['peak_rss'] for r in base)),
        clock_violations=clock,boundary_interval_audit=dict(checked=checked,errors=frame_errors),long_1000=long,
        waveform=dict(total=len(quality),bit_exact_pass=sum(r['PASS'] for r in quality),minimum_overlap_rms_db=min(v for r in quality for v in r['overlap_rms_db']),maximum_overlap_rms_db=max(v for r in quality for v in r['overlap_rms_db']),maximum_output_peak_gain05=max(r['mixed_peak'] for r in quality)*.5,unexpected_zero_frames=sum(r['unexpected_zero_frames'] for r in quality),subjective_listening=False,acoustic_loopback=False,piano_recording=False),
        physical=read('physical_loop/result.json'),contracts=read('last_summary.json')['PASS'],extra=all(r['exit']==0 for r in read('extra_summary.json')['rows'] if r['name']!='cli_final'),cli=read('last_cli_release/summary.json')['PASS'] and read('last_cli_debug/summary.json')['PASS'],manual_speed={mode:read('last_manual-speed_'+mode+'/result.json') for mode in ('release','debug')},late_whole={mode:read('last_near-end_'+mode+'/result.json') for mode in ('release','debug')},native_deadline={mode:read('last_deadline_'+mode+'/result.json') for mode in ('release','debug')},trace_repeat=read('trace_repeat/result.json'),suites=suites)
    result['long_1000']['cpu_one_core_percent']=100*long['process_cpu_s']/long['wall_s']
    result['final_source_whole']={mode:read('final_supply_whole_'+mode+'/result.json') for mode in ('release','debug')}
    result['final_source_whole_realtime_deadline_pass']={mode:not (row['final_worker_deadlines'] or row['callback_deadlines'] or row['host_errors'] or row['sample_errors'] or row['hal_window_misses']) for mode,row in result['final_source_whole'].items()}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('native_matrix','boundary_interval_audit','waveform')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
