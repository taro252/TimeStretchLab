"""今回の全Native失敗を抽出する。再実行成功やPCM一致で失敗を取り消さない。"""
import csv
import json
import math
from collections import Counter
from phase59_fix2_start_state import ROOT, OUT, sha

METRICS=('missing_frames','underrun_calls','underruns','fifo_underruns','rejected_writes','callback_deadlines','hal_window_misses',
         'host_missing','host_backwards','host_cadence_errors','host_errors','sample_errors',
         'pcm_mismatches','callback_cpp_allocations','callback_cpp_new',
         'rt_cpp_allocations','realtime_cpp_allocations','realtime_cpp_new_calls','dsp_cpp_new_calls','workgroup_deadline_misses',
         'callback_records_dropped','dropped','invalid_host','invalid_sample')


def main():
    base=ROOT/'build/phase59_fix2_artifacts';summaries=[];totals=Counter();failed=[];flags=Counter();scalars=[]
    for path in sorted(base.rglob('summary.json')):
        # Binary build trees can contain copied old results; only real audio
        # summary schemas qualify. PCM engines lack callback counters.
        d=json.loads(path.read_text())
        if not isinstance(d,dict) or not ('callback_calls' in d or ('source_rate' in d and 'calls' in d)):continue
        item=dict(path=str(path),sha256=sha(path),PASS=bool(d.get('PASS',False)),metrics={k:d[k] for k in METRICS if k in d})
        summaries.append(item)
        for k,v in item['metrics'].items():totals[k]+=int(v)
        if not item['PASS']:failed.append(item)
        cb=path.parent/'callbacks.csv'
        if cb.exists():
            extra=path.parent/'callback_timestamps.csv';by_sequence={}
            if extra.exists():
                with extra.open() as file:by_sequence={r['sequence']:r for r in csv.DictReader(file)}
            with cb.open() as file:
                for row in csv.DictReader(file):
                    if 'flags' not in row:continue
                    flags['callback_rows']+=1;f=int(row['flags'])
                    flags['invalid_sample_rows']+=not bool(f&1);flags['invalid_host_rows']+=not bool(f&2)
                    scalar=row.get('rate_scalar',by_sequence.get(row['sequence'],{}).get('rate_scalar'))
                    if f&4 and scalar is not None:
                        value=float(scalar)
                        if math.isfinite(value) and value>0:scalars.append(value)
                        else:flags['valid_rate_scalar_bad_value']+=1
                    elif f&4:flags['valid_rate_scalar_not_recorded']+=1
                    else:flags['rate_scalar_flag_invalid']+=1
    legacy=[]
    for tag in ('investigation','final','same_rate'):
        path=OUT/('legacy_'+tag)/'rows.json'
        rows=json.loads(path.read_text())
        legacy.append(dict(tag=tag,sessions=len(rows),failed=[r for r in rows if not r['PASS']],
                           missing_frames_sum_observed=sum(int(r['summary']['missing_frames']) for r in rows if 'missing_frames' in r['summary']),
                           missing_frames_unmeasured_sessions=sum('missing_frames' not in r['summary'] for r in rows)))
    deep=json.loads((OUT/'legacy_deep/rows.json').read_text())
    legacy.append(dict(tag='deep',sessions=len(deep),failed=[r for r in deep if not r['PASS']],
                       missing_frames=sum(int(r['summary']['missing_frames']) for r in deep)))
    trace_legacy=[]
    for name in ('legacy_old_math','legacy_current','legacy_synced','legacy_delayed'):
        folder=base/(name+'_trace_native');path=folder/'summary.txt'
        if path.exists():
            d=dict(line.split('=',1) for line in path.read_text().splitlines() if '=' in line)
            trace_legacy.append(dict(name=name,path=str(path),sha256=sha(path),summary=d))
    result=dict(native_json_sessions=len(summaries),native_json_passed=sum(r['PASS'] for r in summaries),
                native_json_failures=failed,measured_counter_sums=dict(totals),timestamp_flag_scan=dict(flags),
                valid_recorded_rate_scalar=dict(rows=len(scalars),minimum=min(scalars,default=None),maximum=max(scalars,default=None)),
                all_native_json_records=summaries,legacy_comparisons=legacy,legacy_trace_trials=trace_legacy,
                historical_failures_preserved=True,physical_audio_continuity_verified=False,
                scope='JSON Native経路377実行のcounter/flags集計。旧製品TXT経路はlegacy_comparisons/legacy_trace_trialsに別集計し、JSONのmissing 0を旧製品へ拡張しない。正式190/36/8/40と追加研究はREPORTで分離。複数カウンターは同一異常を重複して数え得る。OS欠測フォルトは0にしない。')
    (OUT/'FINAL_MEASUREMENTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('Native json',len(summaries),'failed',len(failed),'legacy failures',sum(len(r['failed']) for r in legacy),flush=True)


if __name__=='__main__':main()
