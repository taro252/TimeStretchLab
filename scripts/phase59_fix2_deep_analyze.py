"""別ビルドの供給境界と自プロセスMach標本を、寿命内だけ照合する。"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def load(path):
    with path.open() as file:return [{k:int(v) for k,v in r.items()} for r in csv.DictReader(file)]


def analyze(folder):
    status=json.loads((folder/'supply_status.json').read_text());scale=status['timebase_numer']/status['timebase_denom']
    events=load(folder/'supply_events.csv');samples=load(folder/'supply_samples.csv')
    lives={};open_lives={};scopes=[];stacks=defaultdict(list);unpaired=[]
    for event in events:
        key=(event['owner'],event['thread']);kind=event['kind']
        if kind==1:open_lives[key]=event
        elif kind==2:
            begin=open_lives.pop(key,None)
            if begin:lives[key]=(begin['after_ticks'],event['before_ticks'])
            else:unpaired.append(event)
        elif kind%2==0:stacks[key+(kind,)].append(event)
        else:
            stack=stacks[key+(kind-1,)]
            if not stack:unpaired.append(event);continue
            begin=stack.pop();wall=(event['before_ticks']-begin['after_ticks'])*scale
            scopes.append(dict(kind=kind-1,owner=event['owner'],thread=event['thread'],
                               begin=begin,end=event,wall_ns=wall,cpu_ns=event['cpu_ns']-begin['cpu_ns'],
                               wall_minus_sampled_cpu_ns=max(0,wall-(event['cpu_ns']-begin['cpu_ns']))))
    valid=[];invalid=[]
    for sample in samples:
        life=lives.get((sample['owner'],sample['thread']))
        (valid if sample['result']==0 and life and life[0]<=sample['before_ticks']<=sample['after_ticks']<=life[1] else invalid).append(sample)
    session_tids=defaultdict(set)
    for path in [*folder.glob('worker_*.csv'),*folder.glob('retired_worker_*.csv')]:
        with path.open() as file:
            for row in csv.DictReader(file):
                if int(row['thread_id']):session_tids[row['session']].add(int(row['thread_id']))
    shortages=[]
    for path in sorted(folder.glob('callbacks_*.csv')):
        with path.open() as file:
            for cb in csv.DictReader(file):
                missing=int(cb['wanted'])-int(cb['received'])
                if missing<=0:continue
                instant=int(cb['start_ns'])/scale
                writes=sorted((s for s in scopes if s['kind']==50 and s['begin']['frames']>0 and s['end']['write']-s['begin']['write']==s['begin']['frames'] and s['thread'] in session_tids[cb['session']] and s['end']['after_ticks']>instant),key=lambda s:s['end']['after_ticks'])
                nxt=writes[0] if writes else None
                feeds=[s for s in scopes if nxt and s['kind']==20 and s['owner']==nxt['owner'] and s['begin']['after_ticks']<=nxt['begin']['before_ticks']<=s['end']['before_ticks']]
                feed=feeds[-1] if feeds else None
                active=[s for s in scopes if nxt and s['owner']==nxt['owner'] and s['begin']['after_ticks']<=instant<=s['end']['before_ticks']]
                window=[s for s in valid if nxt and s['owner']==nxt['owner'] and instant-200e6/scale<=s['before_ticks']<=nxt['end']['after_ticks']]
                shortages.append(dict(callback=cb,source=str(path),missing_frames=missing,next_write=nxt,feed_for_next_write=feed,
                                      pcm_positive_evidence_before_shortage=bool(feed and feed['begin']['after_ticks']<instant),
                                      active_scopes_at_shortage=active,mach_samples_near_shortage=window))
    for scope in scopes:
        selected=[s for s in valid if s['owner']==scope['owner'] and s['thread']==scope['thread'] and scope['begin']['after_ticks']<=s['before_ticks']<=s['after_ticks']<=scope['end']['before_ticks']]
        scope['interior_samples']=len(selected);scope['sampled_states']=dict(Counter(s['state'] for s in selected))
    summary=dict(path=str(folder),events=len(events),samples=len(samples),valid_lifetime_samples=len(valid),
                 invalid_or_outside_lifetime_samples=len(invalid),complete_worker_lifetimes=len(lives),
                 unpaired_events=len(unpaired)+len(open_lives)+sum(len(s) for s in stacks.values()),
                 measurement_export_complete=bool(status['event_export_ok'] and status['sample_export_ok'] and not status['event_dropped'] and not status['sample_dropped']),
                 missing_callbacks=len(shortages),missing_frames=sum(s['missing_frames'] for s in shortages),
                 fifo_write_scopes=sum(s['kind']==50 for s in scopes),
                 confirmed_write_scopes=sum(s['kind']==50 and s['begin']['frames']>0 and s['end']['write']-s['begin']['write']==s['begin']['frames'] for s in scopes),
                 shortages_with_positive_generated_pcm_evidence=sum(s['pcm_positive_evidence_before_shortage'] for s in shortages),
                 sampled_states=dict(Counter(s['state'] for s in valid)),sampled_priorities=dict(Counter(s['priority'] for s in valid)),
                 max_validation_ms=max([s['wall_ns']/1e6 for s in scopes if s['kind'] in (22,32)]+[0]),
                 longest_scopes=sorted(scopes,key=lambda s:s['wall_ns'],reverse=True)[:12])
    return summary,dict(summary=summary,shortages=shortages,scopes=scopes,invalid_samples=invalid,status=status)


def main():
    folders=sorted(p for p in (ROOT/'build/phase59_fix2_artifacts/deep_legacy/trials').glob('*') if p.is_dir())
    delayed=ROOT/'build/phase59_fix2_artifacts/legacy_delayed_trace_native'
    if (delayed/'supply_status.json').exists():folders.append(delayed)
    assert folders and all((p/'supply_status.json').exists() for p in folders)
    destination=ROOT/'build/phase59_fix2_artifacts/deep_legacy/analysis';destination.mkdir()
    results=[]
    for folder in folders:
        summary,payload=analyze(folder);path=destination/(folder.name+'.json')
        with path.open('x') as file:json.dump(payload,file,ensure_ascii=False,indent=2);file.write('\n')
        summary['payload']=str(path);summary['payload_sha256']=sha(path);results.append(summary)
        print(folder.name,'missing',summary['missing_frames'],'valid_samples',summary['valid_lifetime_samples'],flush=True)
    (OUT/'LEGACY_DEEP_ANALYSIS.json').write_text(json.dumps(dict(trials=results,
        scope='供給観測だけの別ビルド。実時間workerへ昇格していない。state 1=RUNNINGは実行可能の標本で連続CPUの証明ではない。state 3=WAITINGも待機先や因果を特定しない。寿命外・取得失敗は未観測。記録関数の前後を除いた内部だけを区間とする。'),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
