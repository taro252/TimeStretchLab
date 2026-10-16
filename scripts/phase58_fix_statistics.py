"""Aggregate all retained native trials without removing failed measurements."""
import bisect
import collections
import csv
import json
import math
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase58_fix'

def distribution(values):
    values=sorted(values)
    if not values:return None
    def q(p):return values[max(0,math.ceil(p*len(values))-1)]
    return dict(n=len(values),min=values[0],median=statistics.median(values),p95=q(.95),p99=q(.99),max=values[-1])

def summarize(name,paths):
    records=[];blocks=[];rtblocks=[];sample_policy=collections.Counter();active_samples=0
    for p in sorted(paths):
        s=json.loads(p.read_text())
        if 'dsp_thread' not in s:continue
        records.append(dict(path=str(p.relative_to(ROOT)),summary=s))
        f=p.with_name('worker.csv')
        data=list(csv.DictReader(f.open())) if f.exists() else []
        for b in data:
            b['session']=str(p.parent.relative_to(ROOT));blocks.append(b)
            if b.get('realtime')=='1':rtblocks.append(b)
        f=p.with_name('thread_samples.csv')
        intervals=[(float(b['start_s']),float(b['published_s'])) for b in data if b.get('realtime')=='1']
        starts=[b[0] for b in intervals]
        if f.exists():
            for sample in csv.DictReader(f.open()):
                before,after=float(sample['before_s']),float(sample['after_s'])
                i=bisect.bisect_right(starts,before)-1
                if i>=0 and after<=intervals[i][1]:
                    active_samples+=1
                    key=(int(sample['result']),int(sample['policy']),int(sample['current_priority']))
                    sample_policy[str(key)]+=1
    summaries=[r['summary'] for r in records]
    counters=('missing_frames','missing_calls','rejected_writes','callback_deadlines','hal_misses',
              'host_missing','host_backwards','host_cadence_errors','sample_errors','callback_formats',
              'pcm_mismatches','callback_cpp_allocations','realtime_cpp_new_calls',
              'workgroup_deadline_misses','workgroup_policy_errors','workgroup_join_errors',
              'workgroup_restore_errors','workgroup_interval_errors','workgroup_query_errors',
              'workgroup_wait_errors','workgroup_wake_errors','worker_profile_dropped','detail_dropped',
              'thread_samples_dropped','thread_sample_errors')
    result=dict(name=name,sessions=len(summaries),passed=sum(bool(s['PASS']) for s in summaries),
        failed=sum(not s['PASS'] for s in summaries),audio_pass=sum(bool(s['audio_pass']) for s in summaries),
        measurement_valid=sum(bool(s['measurement_valid']) for s in summaries),
        workgroup_sessions=sum(bool(s.get('workgroup_enabled')) for s in summaries),
        workgroup_policy_measured_sessions=sum(bool(s.get('workgroup_policy_measured')) for s in summaries),
        realtime_cpp_allocations_measured_sessions=sum(bool(s.get('realtime_cpp_allocations_measured')) for s in summaries),
        callback_cpp_allocations_measured_sessions=sum(bool(s.get('allocation_measured')) for s in summaries),
        pcm_prefix_exact=sum(bool(s['pcm_prefix_exact']) for s in summaries),
        pcm_complete_exact=sum(bool(s['pcm_complete_exact']) for s in summaries),
        failures=[r for r in records if not r['summary']['PASS']],
        counter_totals={k:sum(s[k] for s in summaries) if summaries and all(s.get(k) is not None for s in summaries) else None for k in counters},
        metric_distributions={k:distribution([s[k] for s in summaries if s.get(k) is not None]) for k in
            ('max_consecutive_missing','fifo_high_water','max_dsp_wall_s','max_dsp_cpu_s','max_publication_gap_s',
             'analysis_wait_s','backpressure_wait_s','analysis_worker_cpu_s','dsp_worker_cpu_s',
             'process_cpu_s','peak_rss_bytes','ready_s','resident_ready_s','first_callback_s')},
        active_block_thread_samples=active_samples,active_block_sample_policy_priority=dict(sample_policy),
        scheduling_delay_per_session_s=None,unknown_wait_per_session_s=None,
        scheduling_delay_scope='Continuous state available only in OS trace cohorts; samples do not fill gaps')
    if not result['workgroup_sessions']:
        for key in counters:
            if key.startswith('workgroup_'):result['counter_totals'][key]=None
    if not result['realtime_cpp_allocations_measured_sessions']:result['counter_totals']['realtime_cpp_new_calls']=None
    for label,data in (('all',blocks),('realtime',rtblocks)):
        result[label+'_blocks']=dict(count=len(data),wall_s=distribution([float(b['wall_s']) for b in data]),
            cpu_s=distribution([float(b['cpu_s']) for b in data]),
            non_cpu_s=distribution([float(b['wall_s'])-float(b['cpu_s']) for b in data]),
            publication_gap_s=distribution([float(b['publication_gap_s']) for b in data]))
    return result

def main():
    cohorts={}
    for name in ('before_repeat20','before_repeat100','candidate_v2_smoke20','candidate_v2_evaluation100',
                 'final_normal300','cpu_load100','profile_off20','resident_standard20',
                 'v3_normal300','v3_cpu100','v3_profile_off20'):
        folder=OUT/name
        if folder.exists():cohorts[name]=summarize(name,folder.glob('run_*/summary.json'))
    for name in ('native_grid','native_lifecycle_load','native_long','v3_grid','v3_lifecycle_load','v3_long'):
        folder=OUT/name
        if folder.exists():cohorts[name]=summarize(name,folder.glob('*/native/**/summary.json'))
    for prefix,folder in (('startup_',OUT/'native_startup'),('v3_startup_',OUT/'v3_startup')):
        if folder.exists():
            for method in ('original','fix'):
                cohorts[prefix+method]=summarize(prefix+method,folder.glob('*/repeat_*/'+method+'/*/summary.json'))
    result=dict(cohorts=cohorts,all_failures_retained=True,percentiles='nearest rank; no failed trials excluded',
                limits='C++ allocations only; bounded samples may be dropped; no system-wide memory-pressure claim')
    for label,startup in (('legacy_startup',OUT/'native_startup/rows.json'),('v3_legacy_startup',OUT/'v3_startup/rows.json')):
      if startup.exists():
        rows=json.loads(startup.read_text());legacy=[s for r in rows for s in r['legacy'] if s]
        counters=('callback_deadlines','hal_misses','host_missing','host_backwards','host_cadence_errors',
                  'sample_errors','format_errors','missing_frames','rejected_writes')
        result[label]=dict(sessions=len(legacy),
            counter_totals={k:sum(s[k] for s in legacy) for k in counters},
            published_prefix_exact=sum(bool(s.get('published_pcm_prefix_exact')) for s in legacy),
            callback_cpp_allocations=None,allocation_measured=False,
            scope='Startup legacy harness measures timing and raw published prefix; no callback allocation hook')
    (OUT/'native_statistics.json').write_text(json.dumps(result,indent=2)+'\n')
    print({name:(s['sessions'],s['passed'],s['failed']) for name,s in cohorts.items()})

if __name__=='__main__':main()
