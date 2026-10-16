"""位相細分計測の包含関係と処理量を、保存済みデータから集計する。"""
import argparse
import collections
import csv
import json
import math
import statistics
from pathlib import Path
from phase57_study import sha


def correlation(x,y):
    xm=statistics.mean(x);ym=statistics.mean(y)
    a=sum((v-xm)**2 for v in x);b=sum((v-ym)**2 for v in y)
    return sum((v-xm)*(w-ym) for v,w in zip(x,y))/math.sqrt(a*b) if a and b else None


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('profile',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();manifest=json.loads((args.profile/'manifest.json').read_text())
    data=Path(manifest['artifact_directory']);rows=[]
    for row in json.loads((args.profile/'rows.json').read_text()):
        folder=data/f"{row['index']:02d}_{row['label']}_{row['preset']}_cpu{row['cpu']}_{row['profile']}"
        result={k:row[k] for k in ('index','label','preset','cpu','profile','realtime_cpu_ms','realtime_wall_ms','phase_cpu_ms')}
        result.update(deadline_misses=row['native']['workgroup_deadline_misses'],pcm_complete_exact=row['pcm_complete_exact'])
        if (folder/'phase_frames.csv').exists():
            frames=collections.defaultdict(list)
            for r in csv.DictReader((folder/'phase_frames.csv').open()):frames[int(r['output_start'])].append(r)
            blocks=[]
            for r in csv.DictReader((folder/'worker.csv').open()):
                if r['realtime']!='1' or int(r['output_start'])==int(r['output_end']):continue
                values=frames[int(r['output_start'])]
                blocks.append(dict(output_start=int(r['output_start']),cpu_ms=float(r['cpu_s'])*1000,wall_ms=float(r['wall_s'])*1000,
                    phase_cpu_ms=float(r['phase_cpu_s'])*1000,frames=sum(int(x['frames']) for x in values),shared_peaks=sum(int(x['shared_peaks']) for x in values),
                    max_shared_peaks=max(int(x['max_shared_peaks']) for x in values),neighborhood_evaluations=sum(int(x['neighborhood_evaluations']) for x in values)))
            result['work_cpu_correlations']={k:correlation([b[k] for b in blocks],[b['cpu_ms'] for b in blocks]) for k in ('frames','shared_peaks','neighborhood_evaluations')}
            result['worst_blocks']=sorted(blocks,key=lambda b:b['cpu_ms'],reverse=True)[:10]
            result['historical_positions']=[b for b in blocks if b['output_start'] in (342016,3194880,3438592)]
        stacks=collections.defaultdict(list);totals=collections.defaultdict(lambda:dict(calls=0,wall_ms=0.,cpu_ms=0.,max_cpu_ms=0.))
        if (folder/'detail.csv').exists():
            for r in csv.DictReader((folder/'detail.csv').open()):
                key=(int(r['stage']),int(r['scope']))
                if int(r['stage']) not in (2,20,21,23,24):continue
                if r['begin']=='1':stacks[key].append(r)
                elif stacks[key]:
                    start=stacks[key].pop();v=totals[key];cpu=(float(r['cpu_s'])-float(start['cpu_s']))*1000
                    v['calls']+=1;v['wall_ms']+=(float(r['at_s'])-float(start['at_s']))*1000;v['cpu_ms']+=cpu;v['max_cpu_ms']=max(v['max_cpu_ms'],cpu)
        result['focused_substages']=[dict(stage=k[0],scope=k[1],**v) for k,v in sorted(totals.items())]
        result['unclosed_scopes']=sum(len(v) for v in stacks.values())
        rows.append(result)
    result=dict(source=str(args.profile.resolve()),driver_sha256=sha(Path(__file__)),rows=rows,
        scope='stage20は21を含み、stage2は20/23/24を含む。包含値を合計して全体処理時間に加えない。相関は因果の証明ではない。OS状態はこのCSVだけでは未測定。')
    with args.output.open('x') as file:file.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
