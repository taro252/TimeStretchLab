"""Post-run dependency budgets and controlled-pause physics; no DSP work."""
import csv,json
from pathlib import Path

def analyze(path,row):
    path=Path(path);rate=float(row['dsp_sample_rate'])
    plans=list(csv.DictReader((path/'replay.csv').open()));budgets=[]
    for p in plans:
        if 'immutable_low' not in p:continue
        asked=int(p['requested_output']);boundary=asked;parts={};raw={}
        for name,keys in [('published',['published']),('prepared',['prepared']),('fft',['immutable_low','immutable_mid','immutable_high']),('ola',['ola_low','ola_mid','ola_high']),('fir',['fir250_fence','fir3500_fence']),('density_horizon',['density_horizon_low','density_horizon_mid','density_horizon_high'])]:
            target=max(int(p[k]) for k in keys);raw[name]=target
            new=max(boundary,target);parts[name]=(new-boundary)*1000/rate;boundary=new
        assert boundary==int(p['fence'])
        applied=int(p['applied_output']);complete=int(p['completion_output'])
        holds={k:int(p[k])*1000/rate for k in ('defer_event_samples','defer_gap_samples','ramp_event_samples','ramp_gap_samples')}
        budgets.append(dict(generation=int(p['generation']),direction=f"{float(p['from']):.2f}->{float(p['target']):.2f}",
            requested_output=asked,forbidden_fence=boundary,raw_boundaries=raw,incremental_budget_ms=parts,
            forbidden_prefix_ms=(boundary-asked)*1000/rate,fifo_at_plan_frames=int(p['fifo_at_plan']),fifo_at_plan_ms=int(p['fifo_at_plan'])*1000/rate,
            fence_to_apply_ms=(applied-boundary)*1000/rate,ramp_output_ms=(complete-applied)*1000/rate,
            protection_holds_ms=holds,held_frames=int(p['held_frames']),safe_frames=int(p['safe_frames_used']),
            density_input=int(p['density_input']),density_output=int(p['density_output']),
            map_apply_to_density_ms=(int(p['density_output'])-applied)*1000/rate if int(p['density_output']) else None,
            note='Boundary budgets use sequential max and overlap; they are not independent causal latencies. Ramp progress sums min(oldHop,targetHop)-1 in safe intervals, not a guaranteed 50ms audible ramp.'))
    result=dict(latency_dependency_budgets=budgets)
    if row.get('controlled_stall_configured')=='1':
        start=int(row['controlled_stall_start_mach_ns']);end=int(row['controlled_stall_end_mach_ns'])
        measured=int(row['controlled_stall_measurement_end_mach_ns']);stock=int(row['controlled_stall_fifo_before'])
        callbacks=list(csv.DictReader((path/'callbacks.csv').open()));workers=list(csv.DictReader((path/'workers.csv').open()))
        following=[w for w in workers if int(w['published_mach_ns'])>=end]
        next_pub=int(following[0]['published_mach_ns']) if following else None
        fully_before=[c for c in callbacks if int(c['callback_start_mach_ns'])>=measured and next_pub is not None and int(c['callback_end_mach_ns'])<next_pub]
        potentially_before=[c for c in callbacks if int(c['callback_end_mach_ns'])>=start and next_pub is not None and int(c['callback_start_mach_ns'])<next_pub]
        demand_min=sum(int(c['wanted']) for c in fully_before);demand_max=sum(int(c['wanted']) for c in potentially_before)
        missing_before=sum(int(c['wanted'])-int(c['received']) for c in potentially_before)
        window_end=(next_pub or end)+int(1e9)
        affected=[c for c in callbacks if start<=int(c['callback_start_mach_ns'])<=window_end and int(c['wanted'])>int(c['received'])]
        natural=[c for c in callbacks if (int(c['callback_start_mach_ns'])<start or int(c['callback_start_mach_ns'])>window_end) and int(c['wanted'])>int(c['received'])]
        last_short=int(affected[-1]['sequence']) if affected else None
        recovered=next((c for c in callbacks if last_short is not None and int(c['sequence'])>last_short and int(c['wanted'])>0 and c['wanted']==c['received']),None)
        first_full=next((w for w in following if int(w['fifo_after_write'])>=int(row['controlled_stall_fifo_goal'])),None)
        lower=max(0,demand_min-stock);upper=max(0,demand_max-stock)
        injection_valid=(row['controlled_stall_triggered']=='1' and row['controlled_stall_cancelled']=='0' and stock==int(row['controlled_stall_fifo_goal']) and end>start and
                         (end-start)/1e6>=float(row['controlled_stall_requested_ms']) and next_pub is not None)
        result['controlled_pause']=dict(INJECTION_VALIDITY='PASS' if injection_valid else 'FAIL',requested_ms=float(row['controlled_stall_requested_ms']),
            measured_ms=(end-start)/1e6,stock_frames=stock,theoretical_stock_ms=stock*1000/rate,
            stock_measurement_bracket_us=(measured-start)/1000,first_publication_after_end_ms=(next_pub-end)/1e6 if next_pub else None,
            effective_supply_stop_ms=(next_pub-start)/1e6 if next_pub else None,
            first_missing_callback_ms=(int(affected[0]['callback_start_mach_ns'])-start)/1e6 if affected else None,
            first_missing_hal_ms=(int(affected[0]['host_mach_ns'])-start)/1e6 if affected else None,
            affected_missing_frames=sum(int(c['wanted'])-int(c['received']) for c in affected),natural_missing_frames=sum(int(c['wanted'])-int(c['received']) for c in natural),
            predicted_missing_before_next_publication_range=[lower,upper],observed_missing_before_next_publication=missing_before,
            demand_balance_matches=lower<=missing_before<=upper,
            shortage_recovery_after_end_ms=(int(recovered['callback_start_mach_ns'])-end)/1e6 if recovered else None,
            full_stock_recovery_after_end_ms=(int(first_full['published_mach_ns'])-end)/1e6 if first_full else None,
            waveform_eos_match=row.get('PCM_CORRECTNESS')=='PASS' and row.get('eos_drained')=='1',
            note='Injected window extends through 1s after next publication. Outside shortages are counted separately. Callback/FIFO snapshot overlaps produce a bounded demand interval.')
        with (path/'stall_fifo_timeline.csv').open('w',newline='') as stream:
            fields=['sequence','callback_start_mach_ns','host_mach_ns','available_before','wanted','received','pcm_before'];w=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');w.writeheader()
            w.writerows({k:c[k] for k in fields} for c in callbacks if start-100000000<=int(c['callback_start_mach_ns'])<=window_end)
    (path/'phase49_diagnostics.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result
