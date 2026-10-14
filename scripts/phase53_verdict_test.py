"""Deterministic two-session and correction fault injection (not audio PASS trials)."""
import csv,copy,hashlib,json,struct,tempfile
from pathlib import Path
from phase52_verdict import NUMERIC,finalize
from phase53_sessions import verify_run,integrity,CSV_COLUMNS

def write_csv(path,columns,rows):
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');w.writeheader();w.writerows(rows)
def write_kv(path,row):path.write_text(''.join(f'{k}={v}\n' for k,v in row.items()))
with tempfile.TemporaryDirectory(prefix='phase53_gate_') as tmp:
 root=Path(tmp);pcm=struct.pack('<f',.1)*100;ref=root/'oracle.wav';fmt=struct.pack('<HHIIHH',3,1,48000,192000,4,32)
 ref.write_bytes(b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(pcm))+pcm)
 count=0
 def fixture(change=None,first_change=None,corrupt=None,original=None,exit_code=0,route=False):
  global count
  count+=1;run=root/str(count);run.mkdir();first=run/'closed_session_1';first.mkdir()
  for folder,sid,n,reason in [(first,1,20,'RouteChanged' if route else 'User'),(run,2,100,'EOS')]:
   r={k:'0' for k in NUMERIC};r.update(output_frames='100',produced_frames=str(n),consumed_frames=str(n),presented_frames=str(n),sample_rate='48000',callback_allocations_measured='1',raw_pcm_sha256=hashlib.sha256(pcm[:n*4]).hexdigest(),state='Ended' if reason=='EOS' else 'Stopped',reason=reason,eos='1' if reason=='EOS' else '0',route_stopped='1' if reason=='RouteChanged' else '0',AUDIO_QUALITY='PASS',MEASUREMENT_QUALITY='PASS',session=str(sid),initial='.5',preset='candidate',channels='1',generated_frames=str(n),published_frames=str(n),device_raw_frames=str(n),hash_frames=str(n),hash_scope='fifo_published_raw_float32_interleaved_prefix',start_state='Playing',callback_rows='1',callback_calls='1',worker_rows='1',plan_rows='0',operation_rows='0',worker_error='',native_error='',concurrent_renders='0')
   if sid==1 and first_change:r.update(first_change)
   if sid==2 and change:r.update(change)
   write_kv(folder/'summary.txt',r)
   for filename,columns in CSV_COLUMNS.items():
    fields=columns.split(',');values={key:0 for key in fields};records=[]
    if filename=='callbacks.csv':values.update(sequence=1,epoch=1,wanted=n,received=n,requested=n,output=0,sample_time=0,host_ns=1,flags=3);records=[values]
    if filename=='workers.csv':values.update(cycle=1,frames=n,publication_interval_s=-1);records=[values]
    write_csv(folder/filename,fields,records)
  write_kv(run/'lifecycle.txt',dict(remaining_actions=0,restarts=1))
  write_csv(run/'actions.csv',['planned_seconds','type','result'],[])
  write_csv(run/'sessions.csv',['session','folder'],[dict(session=1,folder='closed_session_1'),dict(session=2,folder='.')])
  if corrupt:corrupt(run,first)
  return verify_run(run,ref,exit_code,reference_override={'.':ref,'closed_session_1':ref},original=original)
 good_sessions=fixture();assert good_sessions['VERDICT']=='PASS'
 assert all(s['SESSION_VERDICT']=='PASS' for s in good_sessions['sessions'])
 for field,value in [('raw_pcm_sha256','a'*64),('rejected_writes','1'),('worker_error','injected'),('missing_frames','1'),('MEASUREMENT_QUALITY','FAIL'),('AUDIO_QUALITY','FAIL'),('sample_errors','1')]:
  assert fixture(first_change={field:value})['VERDICT']=='FAIL',field
 assert fixture(corrupt=lambda r,f:(f/'callbacks.csv').unlink())['MEASUREMENT_QUALITY']=='FAIL'
 assert fixture(corrupt=lambda r,f:(r/'callbacks.csv').write_bytes((r/'callbacks.csv').read_bytes()[:-1]))['VERDICT']=='FAIL'
 assert fixture(first_change={'hash_frames':'19'})['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:write_csv(r/'sessions.csv',['session','folder'],[dict(session=2,folder='.')]))['VERDICT']=='FAIL'
 assert fixture(route=True)['VERDICT']=='PASS'
 assert fixture(corrupt=lambda r,f:write_kv(r/'lifecycle.txt',dict(remaining_actions=1,restarts=1)))['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:(r/'actions.csv').unlink())['VERDICT']=='FAIL'
 assert fixture(exit_code=2)['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:(r/'callbacks.csv').write_text((r/'callbacks.csv').read_text().replace('start_ns,','').replace('1,1,0,','1,1,',1)))['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:(r/'callbacks.csv').write_text('sequence,wanted,received,output,sample_time,host_ns\n2,100,100,0,0,1\n'))['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:(r/'workers.csv').write_text('cycle,frames\n1,90\n'))['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:(r/'operations.csv').write_text('session,generation,status\n2,0,Complete'))['VERDICT']=='FAIL'
 assert fixture(original={'MEASUREMENT_QUALITY':'FAIL'})['VERDICT']=='FAIL'
 assert fixture(original={'AUDIO_QUALITY':'FAIL'})['VERDICT']=='FAIL'
 assert fixture(change={'raw_pcm_sha256':'b'*64})['VERDICT']=='FAIL'
 assert fixture(corrupt=lambda r,f:(f/'workers.csv').write_text('cycle,frames,cpu_s\n1,20,nan\n'))['VERDICT']=='FAIL'
 assert fixture(first_change={'fifo_frames':'16384','lead_frames':'12288','block_frames':'2048','qos':'inherited'})['VERDICT']=='FAIL'
 # Only reference correction may replace PCM failure; other failures remain sticky.
 good=fixture();session=good['sessions'][-1];base=dict(session,PCM_CORRECTNESS='FAIL')
 correction={'reason':'reference EOS only','before':{'PCM_CORRECTNESS':'FAIL'},'after':{'PCM_CORRECTNESS':'PASS','reference_sha256':'a'*64}}
 assert finalize(base,0,[session],session['evidence'],pcm_correction=correction)['VERDICT']=='PASS'
 for field in ('CSV_INTEGRITY','MEASUREMENT_QUALITY','AUDIO_QUALITY'):
  bad=dict(base);bad[field]='FAIL';assert finalize(bad,0,[session],session['evidence'],pcm_correction=correction)['VERDICT']=='FAIL'
 assert finalize(base,2,[session],session['evidence'],pcm_correction=correction)['VERDICT']=='FAIL'
 print(f'{count} saved-session fault fixtures + bounded correction tests PASS; injected audio/CSV/PCM failures stay FAIL')
