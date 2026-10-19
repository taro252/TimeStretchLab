"""固定容量callback記録を独立に再計算。既存の閾値を変更しない。"""
import argparse,json,math
from pathlib import Path

def audit(rows):
    errors=[];checked=0;previous=None;counts=dict(host_missing=0,host_backwards=0,cadence=0,sample=0,hal=0,offset=0)
    for row in rows:
        r=row['callback'];rate=row['source_rate'];tolerance=max(100000.,2e9/rate)
        host_valid=bool(r['flags']&2) and bool(r['host_ns']);sample_valid=bool(r['flags']&1) and isinstance(r['sample_time'],(int,float)) and math.isfinite(r['sample_time'])
        # Values emitted by the native process are in its own Mach timebase.
        converted=int(r['host_ticks']*row['mach_numer']/row['mach_denom'])
        if abs(converted-r['host_ns'])>1:errors.append(dict(sequence=r['sequence'],field='Mach conversion'))
        first=previous is None or previous['callback']['clock_epoch']!=r['clock_epoch']
        flags=dict(host_missing=not host_valid,host_backwards=False,cadence=False,sample=bool(r['flags']&1 and not sample_valid),
                   hal=bool(host_valid and r['io_end_ns']>r['host_ns']+tolerance),
                   offset=bool(host_valid and abs(r['start_ns']-r['host_ns'])>1e9))
        if not first:
            p=previous['callback']
            if host_valid and p['flags']&2 and p['host_ns']:
                delta=r['host_ns']-p['host_ns'];expected=math.floor(p['requested']*1e9/rate+.5)
                flags['host_backwards']=delta<=0;flags['cadence']=abs(delta-expected)>tolerance
            if sample_valid and p['flags']&1 and isinstance(p['sample_time'],(int,float)) and math.isfinite(p['sample_time']):
                delta=r['sample_time']-p['sample_time'];flags['sample']=delta<=0 or abs(delta-p['requested'])>2.
            recorded=row['clock']
            for key,value in flags.items():
                if bool(recorded[key])!=value:errors.append(dict(sequence=r['sequence'],field=key,expected=value,actual=recorded[key]))
            checked+=1
        for key,value in flags.items():counts[key]+=int(value)
        spans=row['spans']
        if len(spans)>32:errors.append(dict(sequence=r['sequence'],field='span capacity'))
        for key in ('old_missing','new_missing','affected','padding'):
            if sum(s[key] for s in spans)!=row[key]:errors.append(dict(sequence=r['sequence'],field='span sum '+key))
        previous=row
    return dict(PASS=bool(rows) and checked>0 and not errors,callbacks=len(rows),checked_pairs=checked,errors=errors,counts=counts,
                acoustic_presentation_verified=False,threshold_ns='max(100000, 2e9/source_rate)')

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('trace',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit([json.loads(line) for line in a.trace.read_text().splitlines()]);a.output.write_text(json.dumps(result,indent=2)+'\n');return int(not result['PASS'])
if __name__=='__main__':raise SystemExit(main())
