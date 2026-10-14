#!/usr/bin/env python3
"""App API integration validation. Native and unpaced PCM verdicts stay separate."""
import argparse,csv,hashlib,json,math,struct,subprocess,datetime,os,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase52';BUILD=ROOT/'build'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def kv(p):return dict(line.split('=',1) for line in p.read_text().splitlines() if '=' in line)
def fresh_run(cmd,out,timeout=1200):
 r=subprocess.run(list(map(str,cmd)),text=True,capture_output=True,timeout=timeout)
 (out/'process.log').write_text(r.stdout+r.stderr);return r

def golden():
 out=OUT/'golden_rebuilt';out.mkdir(exist_ok=True);rows=[]
 for manifest in ('phase12','phase28'):
  for entry in csv.DictReader((ROOT/f'results/{manifest}/golden/manifest.csv').open()):
   if entry['speed'] not in ('0.50','0.60','0.70','0.75','0.80'):continue
   name=entry['name']+'_'+entry['speed'].replace('.','');case=out/name
   if case.exists():raise ValueError('Fresh run required '+str(case))
   r=fresh_run([BUILD/'playback_demo',ROOT/entry['input_path'],case,'candidate',entry['speed'],'--offline'],case)
   actual=sha(case/'raw.wav');match=r.returncode==0 and actual==entry['output_sha256']
   rows.append(dict(source=entry['name'],speed=entry['speed'],sha256=actual,match=match,**kv(case/'summary.txt')));print(name,match,flush=True)
 (OUT/'golden_audit.json').write_text(json.dumps(rows,indent=2));assert len(rows)==25 and all(r['match'] for r in rows)

def source(name,seconds):
 from_path=ROOT/f'results/phase31/input/{name}.wav'
 data=from_path.read_bytes();at=12;fmt=None;pcm=None
 while at+8<=len(data):
  tag,size=struct.unpack_from('<4sI',data,at);body=data[at+8:at+8+size];at+=8+size+(size%2)
  if tag==b'fmt ':fmt=body
  if tag==b'data':pcm=body
 kind,ch,rate,_,align,bits=struct.unpack_from('<HHIIHH',fmt)
 assert kind==3 and bits==32
 n=int(seconds*rate);pcm=(pcm*((n*align+len(pcm)-1)//len(pcm)))[:n*align]
 out=OUT/'input';out.mkdir(exist_ok=True);p=out/f'{name}_{seconds}s.wav'
 content=b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<I',16)+fmt[:16]+b'data'+struct.pack('<I',len(pcm))+pcm
 if p.exists():assert p.read_bytes()==content
 else:p.write_bytes(content)
 return p

def run_case(root,name,speed,preset='candidate',seconds=5,actions=(),silent=True,stall=None,stress=False):
 inp=source(name,seconds);tag=f'{name}_{speed:.2f}_{preset}_{len(list(root.glob("*/summary.txt"))):03d}';out=root/tag;out.mkdir()
 command=[BUILD/'playback_demo',inp,out,preset,speed]
 if silent:command+=['--silent']
 if actions:
  schedule=out/'schedule.csv'
  with schedule.open('w') as f:
   f.write('seconds,action,value\n');f.writelines(f'{t},{a},{v}\n' for t,a,v in actions)
  command+=['--actions',schedule]
 if stall:command+=['--stall-ms',stall]
 load=[]
 try:
  if stress:
   # Same load definition as the prior native experiments: eight busy processes.
   for _ in range(8):load.append(subprocess.Popen(['python3','-c','x=1\nwhile True: x=(x*1664525+1013904223)&0xffffffff'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
  r=fresh_run(command,out)
 finally:
  for p in load:p.terminate()
  for p in load:p.wait()
 row=dict(case=str(out.relative_to(ROOT)),source=name,input_sha256=sha(inp),seconds=seconds,preset=preset,initial=speed,stress=stress,exit=r.returncode,actions=list(actions),intentional_stall=stall)
 if not (out/'summary.txt').exists():row.update(AUDIO_QUALITY='FAIL',MEASUREMENT_QUALITY='FAIL',error='missing summary');return row
 row.update(kv(out/'summary.txt'))
 from phase52_verdict import classify
 life=kv(out/'lifecycle.txt')
 row.update(classify(row,r.returncode,expected_route=any(a[1]=='route' for a in actions),remaining_actions=int(life['remaining_actions'])))
 # Same actual request positions/fences/density history, not nominal wall times.
 ref=out/'reference_round_eos.wav';strategy='L2' if preset=='candidate' else 'C'
 reference=subprocess.run(list(map(str,[BUILD/'playback_reference',inp,ref,row['initial'],out/'plans.csv',strategy,'safe-density'])),text=True,capture_output=True,timeout=180)
 (out/'reference.log').write_text(reference.stdout+reference.stderr)
 if reference.returncode==0:
  digest=subprocess.check_output([str(BUILD/'phase45_pcm_hash'),str(ref)],text=True);values=dict(line.split('=',1) for line in digest.splitlines() if '=' in line)
  if row['reason']=='RouteChanged':
   body=ref.read_bytes();at=12
   while body[at:at+4]!=b'data':at+=8+struct.unpack_from('<I',body,at+4)[0]
   expected=hashlib.sha256(body[at+8:at+8+int(row['produced_frames'])*8]).hexdigest()
   row['PCM_CORRECTNESS']='PASS' if expected==row['raw_pcm_sha256'] else 'FAIL'
   row['pcm_scope']='worker-produced prefix, intentional route stop; no EOS claim'
  else:row['PCM_CORRECTNESS']='PASS' if values['pcm_sha256']==row['raw_pcm_sha256'] and int(values['frames'])==int(row['output_frames']) else 'FAIL'
  row['reference_sha256']=sha(ref)
 else:row['PCM_CORRECTNESS']='FAIL';row['reference_error']=reference.stderr
 rows=list(csv.DictReader((out/'callbacks.csv').open()));row['callback_rows']=len(rows)
 cursor=0;presented=0;continuous=True
 for b in rows:
  if int(b['wanted']):continuous&=int(b['output'])==cursor
  cursor+=int(b['received']);presented+=int(b['wanted'])
 continuous&=cursor==int(row['consumed_frames']) and presented==int(row['presented_frames'])
 row['CSV_INTEGRITY']='PASS' if continuous and len(rows)==int(row['callback_calls']) and all(int(b['sequence'])==i+1 for i,b in enumerate(rows)) else 'FAIL'
 row['fifo_minimum']=min((int(b['fifo_before']) for b in rows if int(b['wanted'])),default=0)
 # Independent timing model: host first-frame target already includes the source
 # route's downstream latency; never add output latency twice. No loopback.
 operations=list(csv.DictReader((out/'operations.csv').open()));latencies=[]
 for op in operations:
  if op['status']!='Completed' or op['session']!=row['session']:continue
  start=int(op['apply_output']);end=int(op['complete_output']);sent=int(op['sent_ns']);observed=int(op['observed_ns'])-int(row['bridge_steady_ns'])+int(row['bridge_mach_ns']);found=[]
  for coordinate in (start,end):
   match=next((b for b in rows if int(b['output'])<=coordinate<int(b['output'])+int(b['received'])),None)
   found.append(None if match is None else (int(match['host_ns'])+(coordinate-int(match['output']))*1e9/float(row['sample_rate'])))
  latencies.append(dict(target=op['target'],scheduled_observation_ns=observed,sent_ns=sent,apply_hal_ms=None if found[0] is None else (found[0]-observed)/1e6,completion_hal_ms=None if found[1] is None else (found[1]-observed)/1e6))
 row['operations']=operations;row['hal_operation_delays']=latencies
 row['VERDICT']='PASS' if r.returncode==0 and all(row[k]=='PASS' for k in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','CSV_INTEGRITY')) else 'FAIL'
 # Intentional supply failure: retain AUDIO FAIL, classify fault detection separately.
 if stall:row['FAULT_DETECTION']='PASS' if int(row.get('missing_frames',0))>0 and row['AUDIO_QUALITY']=='FAIL' and r.returncode==2 else 'FAIL'
 (out/'validation.json').write_text(json.dumps(row,indent=2));print(tag,row['VERDICT'],'missing',row.get('missing_frames'),'PCM',row['PCM_CORRECTNESS'],flush=True);return row

def native(suite):
 root=OUT/'native'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S');root.mkdir(parents=True);rows=[]
 def case(*a,**kw):
  row=run_case(root,*a,**kw);rows.append(row);(root/'summary.json').write_text(json.dumps(rows,indent=2));return row
 if suite=='fixed':
  for name in ('mix','drums','vocal','guitar','bass'):
   for speed in (.4,.5,.75,1,1.5,2):case(name,speed)
 elif suite=='controls':
  for name in ('mix','drums','vocal','guitar','bass'):
   case(name,.4,seconds=10,actions=((.6,'speed',2),(.7,'speed',.75),(.8,'speed',.4),(3,'pause',0),(3.3,'resume',0)))
   case(name,2,seconds=10,actions=((.5,'speed',.4),(.6,'speed',1),(.7,'speed',.4)))
   case(name,.4,seconds=10,actions=((.5,'speed',1),(6,'speed',.4)))
  for name in ('mix','drums'):
   case(name,.4,preset='baseline',seconds=10,actions=((.6,'speed',2),(3,'speed',.4)))
   case(name,.5,seconds=5,actions=((.8,'stop',0),(1,'play',0)))
  case('drums',.5,seconds=5,actions=((.5,'route',0),))
  case('drums',.5,seconds=5,stall=450)
 elif suite=='nopause':
  for name in ('mix','drums'):case(name,.4,seconds=10,silent=False,actions=((1,'speed',2),(3,'speed',.4)))
 elif suite=='long':
  for name in ('mix','drums'):case(name,.4,seconds=180,stress=True,actions=((1,'speed',2),(5,'speed',.4),(9,'speed',1),(13,'speed',2),(17,'pause',0),(17.25,'resume',0)))
 elif suite=='audible':
  for name in ('mix','drums','vocal','guitar','bass'):case(name,.4,seconds=10,silent=False,actions=((1,'speed',2),(3,'speed',.4),(5,'pause',0),(5.25,'resume',0)))
  for name in ('mix','drums'):case(name,.5,seconds=5,actions=((.8,'stop',0),(1,'play',0)))
  case('drums',.5,seconds=5,actions=((.5,'route',0),))
  case('drums',.5,seconds=5,stall=450)
 else:raise ValueError(suite)
 print(root,flush=True)
 normal=[r for r in rows if not r.get('intentional_stall')];return 0 if all(r['VERDICT']=='PASS' for r in normal) and all(r.get('FAULT_DETECTION')=='PASS' for r in rows if r.get('intentional_stall')) else 2

def audit():
 prev=json.loads((ROOT/'results/phase51/protected_wav_audit.json').read_text());entries=prev['rows'];assert all(sha(ROOT/r['path'])==r['sha256'] for r in entries)
 tracked=subprocess.check_output(['git','ls-tree','-rz','313ceab','results']).split(b'\0');protected=[]
 for entry in tracked:
  if not entry:continue
  meta,path=entry.split(b'\t',1);mode,kind,before=meta.split();name=os.fsdecode(path)
  if name.startswith('results/phase52/'):continue
  p=ROOT/name;data=os.fsencode(os.readlink(p)) if mode==b'120000' else p.read_bytes()
  after=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest().encode()
  assert before==after,name;protected.append(name)
 (OUT/'protected_audit.json').write_text(json.dumps(dict(wav_count=len(entries),wav_match=True,tracked_count=len(protected),tracked_match=True),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['golden','fixed','controls','long','audible','nopause','audit']);a=p.parse_args()
 if a.mode=='golden':golden()
 elif a.mode=='audit':audit()
 else:raise SystemExit(native(a.mode))
