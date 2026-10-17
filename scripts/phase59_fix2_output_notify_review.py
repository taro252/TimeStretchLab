"""SourceNodeと出力AudioUnit通知を同じhost時刻・実実行窓で比較する。"""
import csv
import json
from collections import defaultdict
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def rows(path):
    with path.open() as file:return list(csv.DictReader(file))


def main():
    minimal=Path(json.loads((OUT/'TRACE_ANALYSIS_minimal_launch.json').read_text())['native'])
    results=[]
    for name,base in [('A_direct',minimal),('D_no_request',ROOT/'build/phase59_fix2_artifacts/dynamic_no_request_trace_native')]:
        notifications=rows(base/'output_notify.csv');callbacks=rows(base/'callbacks.csv');is_minimal='begin_ticks' in callbacks[0]
        pairs=[];pending=defaultdict(list)
        def host(r):return int(r['host_ticks']) if is_minimal else int(r['host_ns'])
        def start(r):return int(r['ticks']) if is_minimal else int(r['start_ns'])
        for n in notifications:
            key=(host(n),float(n['sample_time']),int(n['frames']));flags=int(n['action'] if is_minimal else n['action_flags'])
            if flags&4:pending[key].append(n)
            if flags&8 and pending[key]:pairs.append((pending[key].pop(),n))
        by_host=defaultdict(list)
        for pre,post in pairs:by_host[host(pre)].append((pre,post))
        joined=[]
        for cb in callbacks:
            match=by_host[host(cb)];entry=int(cb['begin_ticks'] if is_minimal else cb['start_ns']);end=int(cb['end_ticks'] if is_minimal else cb['end_ns'])
            unique=len(match)==1;pre,post=match[0] if unique else ({},{})
            au_flags=int(pre.get('flags',pre.get('timestamp_flags','0')))
            valid=bool(int(cb['flags'])&3==3 and au_flags&3==3)
            joined.append(dict(sequence=cb['sequence'],unique_pair=unique,timestamps_valid=valid,
                source_inside_output_notify=unique and start(pre)<=entry<=end<=start(post),
                sample_equal=unique and valid and float(cb['sample_time'])==float(pre['sample_time']),
                requested_frames_equal=unique and int(cb['requested'])==int(pre['frames']),
                au_rate_scalar=pre.get('rate_scalar'),source=cb,output_pre=pre,output_post=post))
        payload=ROOT/'build/phase59_fix2_artifacts'/('output_notify_'+name+'.json')
        payload.write_text(json.dumps(joined,ensure_ascii=False,indent=2)+'\n')
        results.append(dict(configuration=name,callback_records=len(callbacks),notify_records=len(notifications),pairs=len(pairs),
            unique_pairs=sum(r['unique_pair'] for r in joined),valid_timestamps=sum(r['timestamps_valid'] for r in joined),
            source_inside_output_window=sum(r['source_inside_output_notify'] for r in joined),sample_equal=sum(r['sample_equal'] for r in joined),
            requested_frames_equal=sum(r['requested_frames_equal'] for r in joined),first_three=joined[:3],
            au_rate_scalar_unrecorded=sum(r['au_rate_scalar'] is None for r in joined),payload=str(payload),payload_sha256=sha(payload)))
    result=dict(configurations=results,physical_audio_continuity_verified=False,
        scope='A/DともSourceと出力AUは48kHz。AU pre/post通知を比較しており、装置DAC/物理音声の記録ではない。DのAU rateScalarは未保存で補完しない。異常が起きていない試験でのAPI時刻対応で、過去異常の正当性を証明しない。')
    (OUT/'OUTPUT_AUDIOUNIT_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for r in results:print(r['configuration'],r['callback_records'],'pairs',r['unique_pairs'],'inside',r['source_inside_output_window'],'same sample',r['sample_equal'])


if __name__=='__main__':main()
