"""全失敗を保持し、供給完了・公開・消費を同じMach nsで照合する。"""
import argparse
import csv
import json
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def analyze(folder):
    callbacks=[]
    for path in sorted(folder.glob('callbacks_*.csv')):
        callbacks += [dict(r,source=str(path)) for r in csv.DictReader(path.open())]
    callbacks.sort(key=lambda r:int(r['start_ns']))
    workers=[]
    for path in [*folder.glob('worker_*.csv'),*folder.glob('retired_worker_*.csv')]:
        workers += [dict(r,source=str(path)) for r in csv.DictReader(path.open())]
    workers.sort(key=lambda r:int(r['published_mach_ns']))
    shortages=[];jumps=[]
    for row in callbacks:
        missing=int(row['wanted'])-int(row['received'])
        if not missing:continue
        stamp=int(row['start_ns']);session=row['session']
        producer=[w for w in workers if w.get('session')==session]
        before=[w for w in producer if int(w['published_mach_ns'])<=stamp]
        after=[w for w in producer if int(w['published_mach_ns'])>stamp]
        previous=before[-1] if before else None;following=after[0] if after else None
        ready=int(following['pcm_ready_mach_ns']) if following else None
        write=int(following['write_begin_mach_ns']) if following else None
        shortages.append(dict(callback=row,missing_frames=missing,previous_publication=previous,next_publication=following,
                              next_pcm_ready_before_callback=ready<=stamp if ready else None,
                              next_fifo_write_started_before_callback=write<=stamp if write else None,
                              publication_gap_ns=int(following['published_mach_ns'])-int(previous['published_mach_ns']) if following and previous else None,
                              os_state=None,causal_status='OS未観測。生成完了と公開の位置は測定がある場合だけ区別する。'))
    for a,b in zip(callbacks,callbacks[1:]):
        if a['source']!=b['source'] or a['epoch']!=b['epoch']:continue
        flags=int(a['flags'])&int(b['flags']);sample=None;host=None
        if flags&1:sample=float(b['sample_time'])-float(a['sample_time'])-int(a['requested'])
        if flags&2:host=int(b['host_ns'])-int(a['host_ns'])-int(a['requested'])*1e9/44100
        if sample is not None and abs(sample)>2 or host is not None and abs(host)>100000:
            jumps.append(dict(previous=a,current=b,extra_sample_frames=sample,host_progress_error_ns=host,
                              actual_entry_delta_ns=int(b['start_ns'])-int(a['start_ns']),initial_pair=int(b['sequence'])==2))
    logical=[]
    for a,b in zip(callbacks,callbacks[1:]):
        if a['source']==b['source'] and a['session']==b['session'] and int(b['output'])!=int(a['output'])+int(a['received']):
            logical.append(dict(previous=a,current=b))
    return dict(callbacks=len(callbacks),producer_profiles=len(workers),shortages=shortages,clock_jumps=jumps,
                logical_position_discontinuities=logical,
                actions=list(csv.DictReader((folder/'actions.csv').open())) if (folder/'actions.csv').exists() else [],
                seeks=list(csv.DictReader((folder/'seeks.csv').open())) if (folder/'seeks.csv').exists() else [],
                physical_audio_continuity_verified=False)


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--rows',type=Path,required=True)
    parser.add_argument('--name',required=True)
    args=parser.parse_args();data=json.loads(args.rows.read_text())
    rows=[]
    for trial in data:
        folder=Path(trial['command'][4]);details=analyze(folder)
        rows.append(dict(label=trial['label'],repeat=trial.get('repeat'),mode=trial.get('mode'),preset=trial.get('preset'),
                         original_pass=trial['PASS'],source=str(folder),details=details))
    payload=ROOT/'build/phase59_fix2_artifacts'/('legacy_'+args.name+'_timeline.json')
    with payload.open('x') as file:json.dump(rows,file,ensure_ascii=False,indent=2);file.write('\n')
    summary=dict(sessions=len(rows),passed=sum(r['original_pass'] for r in rows),
                 missing_frames=sum(s['missing_frames'] for r in rows for s in r['details']['shortages']),
                 missing_callbacks=sum(len(r['details']['shortages']) for r in rows),
                 clock_discontinuities=sum(len(r['details']['clock_jumps']) for r in rows),
                 payload=str(payload),payload_sha256=sha(payload),rows_source=str(args.rows),rows_source_sha256=sha(args.rows),
                 per_version={label:dict(sessions=sum(r['label']==label for r in rows),passed=sum(r['label']==label and r['original_pass'] for r in rows),
                    missing_frames=sum(s['missing_frames'] for r in rows if r['label']==label for s in r['details']['shortages'])) for label in sorted(set(r['label'] for r in rows))},
                 root_cause_identified=False,failures_preserved=True)
    with (OUT/('LEGACY_ANALYSIS_'+args.name+'.json')).open('x') as file:json.dump(summary,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
