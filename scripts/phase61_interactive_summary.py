"""Summarize measured rows, preserving lifetime counters and operation deltas."""
import argparse,hashlib,json,math,statistics
from pathlib import Path
def rows(p):return [json.loads(x) for x in p.read_text().splitlines()]
def distribution(values):
    values=sorted(values);n=len(values)
    def q(f):
        at=(n-1)*f;lo=math.floor(at);hi=math.ceil(at)
        return values[lo]*(hi-at)+values[hi]*(at-lo) if lo!=hi else values[lo]
    return {'n':n,'min':values[0],'p50':q(.5),'p95':q(.95),'max':values[-1]}
def performance(data):
    result={'cases':len(data),'ready_ms':distribution([r['ready_ms'] for r in data]),'first_new_pcm_callback_ms':distribution([r['first_pcm_ms'] for r in data]),
            'paired_fifo_ready_to_first_pcm_ms':distribution([(r['first_pcm_ns']-r['fifo_ready_ns'])/1e6 for r in data]),
            'hal_estimate_ms':distribution([(r['hal_estimate_ns']-r['accepted_ns'])/1e6 for r in data]),
            'analysis_complete_at_play':sum(r['analysis_complete_at_play'] for r in data),'max_peak_rss_bytes':max(r['peak_rss'] for r in data),
            'operation_delta_totals':{key:sum(r[key] for r in data) for key in data[0] if key.startswith('delta_')},
            'lifetime_counter_maxima':{key:max(r[key] for r in data) for key in data[0] if key.startswith('lifetime_')},'ready_over_200ms':sum(r['ready_ms']>200 for r in data)}
    if 'switch_ready_ns' in data[0]:
        result.update(switch_ready_to_transition_begin_ms=distribution([(r['transition_begin_ns']-r['switch_ready_ns'])/1e6 for r in data]),
                      preparing_to_analysis_ready_ms=distribution([(r['analysis_ready_ns']-r['preparing_ns'])/1e6 for r in data]),
                      old_fifo_at_switch_frames=distribution([r['old_fifo_at_switch'] for r in data]),
                      discarded_for_seek_frames=distribution([r['discarded_for_seek'] for r in data]),
                      transition_frames=sorted(set(r['transition_frames'] for r in data)))
    return result
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);summary={'performance':{},'controls':{},'exact_native':{}}
    for name in ['baseline_mono','performance_mono','baseline_stereo','performance_stereo','early_stereo']:
        data=rows(a.input/name/'rows.jsonl');summary['performance'][name]=performance(data)
        (a.output/(name+'.jsonl')).write_text('\n'.join(map(json.dumps,data))+'\n')
    for folder in sorted(a.input.glob('controls*')):
        if not folder.is_dir():continue
        data=rows(folder/'sessions.jsonl');measured=[r for r in data if not r['destroyed_without_final_diagnostics']]
        keys=['missing','callback_new','heap_calls','heap_frees','callback_deadlines','worker_deadlines','host_errors','sample_errors','hal_errors','raw_errors','output_errors']
        summary['controls'][folder.name]={'cases':len(data),'functional_passed':sum(r['functional'] for r in data),'with_final_native_diagnostics':len(measured),
            'measured_realtime_passed':sum(not any(r[k] for k in keys) and r['lifetime'] for r in measured),
            'totals':{k:sum(r[k] or 0 for r in data) for k in keys},'destroy_native_diagnostics':'unavailable; do not interpret null as zero',
            'device_buffer_frames':sorted({r['device_buffer'] for r in measured})}
        (a.output/(folder.name+'.jsonl')).write_text('\n'.join(map(json.dumps,data))+'\n')
    for folder in sorted(a.input.glob('exact_*')):
        if not folder.is_dir():continue
        data=rows(folder/'sessions.jsonl');summary['exact_native'][folder.name]={'cases':len(data),'functional_passed':sum(r['functional'] for r in data),'realtime_quality_passed':sum(r['quality'] for r in data),
            'worker_deadlines':sum(r['worker_deadlines'] for r in data),'callback_deadlines':sum(r['callback_deadlines'] for r in data)}
    summary['driver_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (a.output/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
