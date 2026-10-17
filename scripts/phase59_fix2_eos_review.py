"""EOSの時刻橋渡しと、appの離脱前のOS policy標本を照合する。"""
import csv
import json
from collections import Counter
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def rows(path):
    with path.open() as file:return list(csv.DictReader(file))


def main():
    modes=json.loads((OUT/'eos_final/summary.json').read_text())['modes'];results=[]
    for mode in modes:
        folder=ROOT/'build/phase59_fix2_artifacts/eos_final'/(mode['build']+'_'+mode['mode'])
        events=rows(folder/'lifetime.csv')
        for session in mode['sessions']:
            s=session['summary'];run=s['run'];scale=int(s['timebase_numer'])/int(s['timebase_denom'])
            marks=[r for r in events if r['run']==run and float(r['pipeline_s'])>=0]
            # All timestamp samples lie between the saved Mach brackets.
            lower=max(int(r['mach_ns'])-int(r['bridge_uncertainty_ns'])/2-float(r['pipeline_s'])*1e9-1 for r in marks)
            upper=min(int(r['mach_ns'])+int(r['bridge_uncertainty_ns'])/2-float(r['pipeline_s'])*1e9+1 for r in marks)
            valid_bridge=lower<=upper
            joined=int(s['joined_ticks'])*scale;left=int(s['left_ticks'])*scale;restored=int(s['restored_ticks'])*scale
            samples=rows(folder/('thread_samples_'+run+'.csv'));known=[];outside=0
            for sample in samples:
                lo=float(sample['before_s'])*1e9+lower;hi=float(sample['after_s'])*1e9+upper
                if valid_bridge and sample['result']=='0' and joined<=lo<=hi<left:
                    known.append(dict(record=sample,mach_lower_ns=lo,mach_upper_ns=hi))
                else:outside+=1
            workers=[r for r in rows(folder/('worker_'+run+'.csv')) if r['realtime']=='1']
            worst=[]
            for w in sorted(workers,key=lambda r:float(r['wall_s'])-float(r['cpu_s']),reverse=True)[:5]:
                begin=int(w['start_ticks'])*scale;end=int(w['end_ticks'])*scale
                interior=[p for p in known if begin<=p['mach_lower_ns']<=p['mach_upper_ns']<=end]
                worst.append(dict(worker=w,non_cpu_s=max(0,float(w['wall_s'])-float(w['cpu_s'])),
                                  interval_interior_samples=len(interior),
                                  sampled_policy_priority=dict(Counter(p['record']['policy']+':'+p['record']['priority'] for p in interior)),
                                  sampled_states=dict(Counter(p['record']['state'] for p in interior))))
            low=[p for p in known if p['record']['policy']!='2']
            results.append(dict(build=mode['build'],mode=mode['mode'],run=run,summary=s,
                clock_bridge_valid=valid_bridge,clock_bridge_offset_ns=[lower,upper],clock_bridge_width_ns=upper-lower,
                samples_inside_join_leave=len(known),samples_outside_join_leave_or_invalid=outside,
                sampled_policy_priority=dict(Counter(p['record']['policy']+':'+p['record']['priority'] for p in known)),
                non_time_constraint_policy_samples_before_app_leave=len(low),first_non_time_constraint_sample=low[0] if low else None,
                app_join_ns=joined,app_leave_ns=left,app_restore_ns=restored,
                realtime_blocks=len(workers),max_realtime_interval_s=max([(int(w['end_ticks'])-int(w['start_ticks']))*scale/1e9 for w in workers]+[0]),
                worst_non_cpu_blocks=worst))
    destination=ROOT/'build/phase59_fix2_artifacts/eos_final/scheduler_review.json'
    destination.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    result=dict(sessions=len(results),functional_pass=all(m['functional_pass'] for m in modes),
        rows=[{k:r[k] for k in ['build','mode','run','clock_bridge_valid','clock_bridge_width_ns','non_time_constraint_policy_samples_before_app_leave','realtime_blocks','max_realtime_interval_s']} for r in results],
        payload=str(destination),payload_sha256=sha(destination),historical_4_8s_explained=False,
        scope='lifetime.csvの実測Mach括弧から時刻差の共通区間を求め、join後/leave前に全体が収まる取得成功標本だけ使う。state1は実行可能で連続CPUの証明ではない。低policyはOSからの観測で、降格理由や過去4.8秒の全因果は未特定。normalは排出前にappが降格している。')
    (OUT/'EOS_FINAL_SCHEDULER_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for r in results:print(r['build'],r['mode'],r['run'],'bridge',r['clock_bridge_width_ns'],'ns; low-policy before leave',r['non_time_constraint_policy_samples_before_app_leave'],flush=True)


if __name__=='__main__':main()
