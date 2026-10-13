#!/usr/bin/env python3
"""Separate native audio, controlled-fault, and latency/candidate conclusions."""
import csv,json,math
from statistics import median
from pathlib import Path
from phase46_forensics import percentile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase50'
def stats(values):return dict(count=len(values),median=median(values) if values else None,p95=percentile(values,.95),max=max(values,default=None))
def main():
    result={}
    resilience=json.loads((OUT/'resilience/summary.json').read_text())
    result['resilience_audio_counts']={v:sum(r['AUDIO_QUALITY']==v for r in resilience) for v in ('PASS','FAIL','INDETERMINATE')}
    result['fault_detection_counts']={v:sum(r['FAULT_DETECTION']==v for r in resilience) for v in ('PASS','FAIL')}
    result['resilience_groups']={}
    for label in ('A','B','C'):
        cases=[r for r in resilience if r['label']==label and not r['stress']]
        result['resilience_groups'][label]=dict(runs=len(cases),missing=sum(r['missing_frames'] for r in cases),
            max_gap_ms=max(r['publication_ms']['max'] for r in cases),min_fifo=min(r['fifo_minimum_active'] for r in cases),
            cpu_seconds=stats([r['cpu'] for r in cases]),rss_mib=stats([r['rss_mib'] for r in cases]))
    latency=json.loads((OUT/'latency/summary.json').read_text())
    groups={};pairs=[]
    for source in ('mix','drums'):
        for label in ('A','C','C_L1'):
            cases=[r for r in latency if r['source']==source and r['label']==label]
            for direction in ('0.40->2.00','2.00->0.40','0.40->1.00','1.00->2.00'):
                ops=[op for r in cases for op in r['operations']['changes'] if op['direction']==direction]
                groups[f'{source}_{label}_{direction}']=dict(map_hal_ms=stats([op['map_node']['estimated_hardware_presentation_ms'] for op in ops]),
                    first_raw_hal_ms=stats([op['first_raw_difference']['estimated_hardware_presentation_ms'] for op in ops]))
        for time in (1,1.85):
            cases={r['label']:r for r in latency if r['source']==source and r['time']==time}
            for index in range(4):
                a,c,l1=(cases[k]['operations']['changes'][index] for k in ('A','C','C_L1'))
                pa,pc,pl=(cases[k]['plans'][index] for k in ('A','C','C_L1'))
                pairs.append(dict(source=source,time=time,direction=a['direction'],
                    lead_penalty_ms=c['map_node']['estimated_hardware_presentation_ms']-a['map_node']['estimated_hardware_presentation_ms'],
                    L1_shortening_ms=c['map_node']['estimated_hardware_presentation_ms']-l1['map_node']['estimated_hardware_presentation_ms'],
                    requested_A=int(pa['requested_output']),requested_C=int(pc['requested_output']),requested_L1=int(pl['requested_output']),
                    nodes={k:dict(fence=int(p['fence']),applied=int(p['applied_output']),complete=int(p['completion_output'])) for k,p in [('A',pa),('C',pc),('L1',pl)]}))
    result['latency_groups']=groups;result['paired_changes']=pairs
    result['native_latency_quality_counts']={v:sum(r['verdict']==v for r in latency) for v in ('PASS','FAIL','INDETERMINATE')}
    result['L2']='NOT_IMPLEMENTED: prioritized stock control and single-factor dependency-fence candidate'
    (OUT/'statistics.json').write_text(json.dumps(result,indent=2,allow_nan=False))
if __name__=='__main__':main()
