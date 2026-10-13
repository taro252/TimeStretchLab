#!/usr/bin/env python3
"""Post-run response estimates. HAL and callback-entry times are NOT equivalent."""
import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from statistics import median
from phase45_store import parse_log
from phase46_forensics import percentile
ROOT=Path(__file__).resolve().parents[1]


def mapped_response(event,operation,frame,rate,device_ms,source_ms):
    offset_ns=(frame-int(event['pcm_before']))*1e9/rate
    entry=int(event['callback_start_mach_ns'])
    flags=int(event.get('timestamp_flags','0'))
    host=int(event['host_mach_ns'])
    host_valid=bool(flags & 2) and host>0 # kAudioTimeStampHostTimeValid
    result=dict(frame=frame,callback_sequence=event.get('sequence','legacy_unmeasured'),
        callback_entry_ms=(entry-operation)/1e6,callback_sample_offset_ms=offset_ns/1e6,
        signed_entry_minus_host_ms=(entry-host)/1e6 if host_valid else None,
        timestamp_flags=flags,source_rate=rate,device_presentation_latency_ms=device_ms,
        source_output_presentation_latency_ms=source_ms,
        hal_frame_time_ms=(host+offset_ns-operation)/1e6 if host_valid else None,
        estimated_hardware_presentation_ms=(host+offset_ns-operation)/1e6+device_ms if host_valid else None,
        acoustic_loopback_measured=False,
        model='HAL host + source-frame offset + device-only presentationLatency; assumes host is hardware transfer time',
        limitations='SourceNode is upstream, not a directly observed AudioDeviceIOProc. SRC timing is approximate; source total latency is not added again.')
    return result


def analyze(path,input_path,first_changes=True):
    path=path.resolve();input_path=input_path.resolve()
    values=parse_log((path/'playback.log').read_text())
    events=list(csv.DictReader((path/'callbacks.csv').open()))
    plan=list(csv.DictReader((path/'replay.csv').open()))
    changes=[dict(re.findall(r'(\w+)=([^ ]+)',line)) for line in (path/'playback.log').read_text().splitlines() if line.startswith('change=')]
    rate=float(values['dsp_sample_rate']);device=float(values['device_presentation_latency_ms'])
    source=float(values['source_output_presentation_latency_ms']) if 'source_output_presentation_latency_ms' in values else None
    def at(frame):return next(e for e in events if int(e['pcm_before'])<=frame<int(e['pcm_before'])+int(e['received']))
    reference=path/'reference.wav'
    if first_changes and not reference.exists():
        run_command([ROOT/'build/phase39_reference',input_path,reference,values['initial_speed'],path/'replay.csv','C','safe-density'],path/'operation_reference.log')
    output=[]
    for index,change in enumerate(changes):
        operation=int(change['operation_mach_ns']);frame=int(change['applied_output'])
        item=dict(generation=int(change['generation']),direction=f"{float(change['from']):.2f}->{float(change['target']):.2f}",
            map_node=mapped_response(at(frame),operation,frame,rate,device,source))
        if first_changes:
            prefix=path/f'operation_prefix_{index}.csv'
            with prefix.open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(plan[0]),lineterminator='\n')
                writer.writeheader();writer.writerows(plan[:index])
            previous=path/f'operation_before_{index}.wav'
            run_command([ROOT/'build/phase39_reference',input_path,previous,values['initial_speed'],prefix,'C','safe-density'],path/f'operation_before_{index}.log')
            got=subprocess.run([str(ROOT/'build/phase45_pcm_hash'),str(reference),str(previous)],capture_output=True,text=True,check=True)
            first=int(parse_log(got.stdout)['first_changed_pcm_frame'])
            item['first_raw_difference']=mapped_response(at(first),operation,first,rate,device,source)
        output.append(item)
    groups={}
    for direction in {v['direction'] for v in output}:
        vals=[r['map_node']['estimated_hardware_presentation_ms'] for r in output if r['direction']==direction and r['map_node']['estimated_hardware_presentation_ms'] is not None]
        groups[direction]=dict(count=len(vals),median_ms=median(vals) if vals else None,
            p95_nearest_rank_ms=percentile(vals,.95),max_ms=max(vals,default=None))
    result=dict(changes=output,direction_stats=groups,
        ordinary_median_definition='average of central two values for even sample count',
        p95_definition='nearest rank ceil(0.95*N), sorted ascending',
        audible_time_measured=False,old_entry_plus_device_model='underestimates HAL lead; retained only in old Phase45 results')
    (path/'operation_phase46.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result


def run_command(args,log):
    result=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,text=True,timeout=1800)
    log.write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(f'Operation replay failed: {log}')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run',type=Path);parser.add_argument('input',type=Path)
    parser.add_argument('--map-only',action='store_true');args=parser.parse_args()
    print(json.dumps(analyze(args.run,args.input,not args.map_only),ensure_ascii=False))
if __name__=='__main__':main()
