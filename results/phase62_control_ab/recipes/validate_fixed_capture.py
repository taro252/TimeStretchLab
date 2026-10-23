"""全spanの固定Exact RAWと独立float32式。warm再ONの旧/新RAWを製品RAWで代用しない。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'results/phase62_terminal_initial/recipes'))
from validate_initial_pcm import Equations,identity,need,read,save,sha,wav_info,pcm,equal,json_lines,flag,FIXED_SHA
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--reference-binary',type=Path,required=True);p.add_argument('--reference-raw',type=Path,required=True);p.add_argument('--reference-map',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);checks={}
save(a.output/'EXPECTED.json',dict(expected=5,ids=['independent_map','raw_all_bits','output_all_bits','coordinates','gain'],capture=str(a.capture.resolve()),input=identity(a.input),reference_binary=identity(a.reference_binary),reference_raw=identity(a.reference_raw),reference_map=identity(a.reference_map),equations=identity(ROOT/'results/phase62_terminal_initial/recipes/validate_initial_pcm.py'),driver=identity(Path(__file__))))
try:
 need(sha(a.reference_binary)==FIXED_SHA,'reference identity');m=read(a.reference_map);info=wav_info(a.input);ch,rate=info['channels'],info['rate'];need(m['channels']==ch and m['rate']==rate and m['input_frames']==info['frames'],'reference input format');need(sha(a.reference_raw)==m['sha256'],'reference RAW SHA');oa,ob=m['positions'];period=ob-oa;width=min(rate//200,period//4);declared=read(a.capture/'EXPECTED.json');need(declared['A']<declared['B'] and read(a.capture/'SUMMARY.json')['status']=='PASS','native result');checks['independent_map']='PASS'
 ref=pcm(a.reference_raw,ch);raw=pcm(a.capture/'raw.f32',ch);output=pcm(a.capture/'output_before_gain.f32',ch);records=json_lines(a.capture/'raw_records.jsonl');spans=json_lines(a.capture/'spans.jsonl');raw_cursor=0;sources=[]
 for i,r in enumerate(records):
  n,at=r['frames'],r['at'];need(0<n<=4096 and r['raw_offset']==raw_cursor and 0<=at<at+n<=len(ref),'RAW range/ordering');equal(raw[raw_cursor:raw_cursor+n],ref[at:at+n],'independent_RAW',a.output,record=i);raw_cursor+=n;sources.append((r['epoch'],at,n))
 need(raw_cursor==len(raw),'RAW uncovered');checks['raw_all_bits']='PASS';eq=Equations('fused');cursor=0;used=[];previous_end=None
 for i,s in enumerate(spans):
  n,at,mix=s['frames'],s['new_at'],s['mixed'];need(0<n<=4096 and s['new_received']==n and 0<=at<at+n<=len(ref) and 0<=mix<=n,'span range/supply');need(previous_end is None or s['callback_frame']==previous_end,'callback gap/duplicate');previous_end=s['callback_frame']+n;expected=ref[at:at+n].copy();used.append((s['new_epoch'],at,n))
  def corrected(values,old=False):
   prefix='old_' if old else '';head,tail=flag(s,prefix+'head'),flag(s,prefix+'tail');need(not(head and tail),'both correction sides')
   if not flag(s,prefix+'periodic'):need(not head and not tail,'correction without periodic');return values
   pos=s['old_at'] if old else at;need(s[prefix+'period_frames']==period and s[prefix+'boundary_frames']==width and s[prefix+'period_offset']==pos-oa and oa<=pos<pos+len(values)<=ob,'independent A/B/period')
   if head or tail:
    equal(np.asarray(s[prefix+'boundary_last'][:ch],dtype='<f4').reshape(1,ch),ref[ob-1:ob],'last endpoint',a.output,span=i);equal(np.asarray(s[prefix+'boundary_first'][:ch],dtype='<f4').reshape(1,ch),ref[oa:oa+1],'first endpoint',a.output,span=i)
   return eq.correction(values,pos-oa,period,width,head,tail,ref[ob-1],ref[oa])
  before=flag(s,'correction_before_mix')
  if before:expected=corrected(expected)
  if mix:
   old=s['old_at'];need(s['old_received']==mix and 0<=old<old+mix<=len(ref) and s['transition_length']==rate//200 and 0<=s['transition_offset']<s['transition_offset']+mix<=s['transition_length'],'mixture coordinates');expected=eq.mix(expected,corrected(ref[old:old+mix],True),s['transition_offset'],s['transition_length']);used.append((s['old_epoch'],old,mix))
  if not before:expected=corrected(expected)
  equal(output[cursor:cursor+n],expected,'independent final output',a.output,span=i);cursor+=n
 need(cursor==len(output),'output uncovered');checks['output_all_bits']='PASS';need(sources==used,'RAW observer vs span ownership');checks['coordinates']='PASS'
 # Renderer observer is before AVAudioEngine mixer. Verify its configured gain
 # separately; this is not a physical gain/loopback measurement.
 source=(ROOT/'src/platform/macos/ProgressiveMacPlaybackEngine.mm').read_text();need('engine.mainMixerNode.outputVolume=.5f' in source,'final mixer gain changed');checks['gain']='PASS';save(a.output/'SUMMARY.json',dict(status='PASS',run_complete=True,expected=5,executed=5,passed=5,checks=checks,raw_frames=len(raw),output_frames=len(output),channels=ch,mixed_frames=sum(s['mixed'] for s in spans),gain=.5,gain_scope='configuration inspection; observer PCM before gain; physical audio NOT_RUN'))
except Exception as e:
 save(a.output/'SUMMARY.json',dict(status='FAIL',run_complete=False,expected=5,executed=len(checks),passed=len(checks),checks=checks,reason=str(e)));raise
