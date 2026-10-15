"""Native trials: preserve all outcomes; require strict saved CSV and counters."""
import argparse,csv,datetime,json,math,subprocess,time
from pathlib import Path
from phase47_evidence import read_csv
from phase53_sessions import ROOT,kv
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--suite',choices=('short','long','mono'),required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
cases=([('mix',30,.4,'candidate','smoke',64,False),('drums',30,.4,'candidate','smoke',64,False),('vocal',30,1.,'candidate','smoke',128,False),('guitar',30,1.5,'candidate','smoke',64,False),('bass',30,.5,'candidate','smoke',256,False),('drums',30,.5,'baseline','smoke',64,False),('drums',30,.4,'candidate','route',64,False)] if a.suite=='short' else [('mix',180,2.,'candidate','long',64,False),('drums',300,2.,'candidate','long',64,False),('drums',180,2.,'candidate','eos',64,True)])
if a.suite=='mono':cases=[('mono_mix',3,.5,'candidate','eos',64,False),('mono_drums',3,2.,'candidate','eos',64,False)]
results=[]
for ordinal,(name,seconds,speed,preset,mode,fade,stress) in enumerate(cases):
 label=f'{ordinal:02}_{name}_{seconds}_{preset}_{mode}';out=a.output/label
 command=list(map(str,[ROOT/'build/phase54_native',ROOT/f'results/phase54/input/{name}_{seconds}s.wav',preset,speed,out,mode,fade]))
 if a.suite=='long':command.append('silent')
 loads=[]
 try:
  if stress:
   for _ in range(8):loads.append(subprocess.Popen(['python3','-c','x=1\nwhile True: x=(x*1664525+1013904223)&0xffffffff'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
  started=datetime.datetime.now().isoformat();run=subprocess.run(command,capture_output=True,text=True,timeout=1200)
 finally:
  for load in loads:load.terminate()
  for load in loads:load.wait()
 (a.output/(label+'.log')).write_text(run.stdout+run.stderr)
 row=dict(case=label,command=command,started=started,stress=stress,exit=run.returncode,CSV_INTEGRITY='PASS',faults=[])
 try:
  saved=kv(out/'summary.txt');row['summary']=saved
  required={'AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','VERDICT','missing_frames','lifetime_missing_frames','callback_rows','callback_overruns','callback_allocations','expected_frames','consumed_frames','eos','route','source_rate','channels','device','device_rate','device_buffer'}
  if not required.issubset(saved):raise ValueError('summary mandatory fields missing')
  for k,v in saved.items():
   if k in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','VERDICT','mode'):continue
   if not math.isfinite(float(v)) or float(v)<0:raise ValueError('invalid summary numeric '+k)
  total=0;quantums=set()
  paths=sorted(out.glob('callbacks_*.csv'))
  if not paths:raise ValueError('callbacks missing')
  for path in paths:
   callbacks,digest=read_csv(path,{'sequence','epoch','session','start_ns','end_ns','host_ns','sample_time','flags','requested','wanted','received','output','fifo'})
   if [int(r['sequence']) for r in callbacks]!=list(range(1,len(callbacks)+1)):raise ValueError('callback sequence')
   for r in callbacks:
    if any(not math.isfinite(float(v)) or float(v)<0 for v in r.values()):raise ValueError('invalid callback value')
    if int(r['received'])>int(r['wanted']) or int(r['wanted'])>int(r['requested']):raise ValueError('callback counts')
    if int(r['end_ns'])<int(r['start_ns']):raise ValueError('callback time')
    quantums.add(int(r['requested']))
   total+=len(callbacks)
  if total!=int(saved['callback_rows']):raise ValueError('saved callback count')
  seeks,_=read_csv(out/'seeks.csv',{'id','session','input','output','speed','status','observed_ns','ready_ns','replans'})
  if sorted(int(r['id']) for r in seeks)!=list(range(1,len(seeks)+1)):raise ValueError('seek ID inventory')
  if any(r['status'] not in ('Completed','Replaced','Cancelled','Rejected','Failed') for r in seeks):raise ValueError('unfinished seeks')
  for r in seeks:
   if any(not math.isfinite(float(v)) or float(v)<0 for k,v in r.items() if k!='status'):raise ValueError('invalid seek value')
   if int(r['ready_ns'])<int(r['observed_ns']) or int(r['observed_ns'])<=0:raise ValueError('seek timestamp ordering')
  read_csv(out/'actions.csv',{'elapsed_s','operation','id','state'})
  row['callback_quantums']=sorted(quantums);row['seek_count']=len(seeks)
  row['PASS']=run.returncode==0 and all(saved[k]=='PASS' for k in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','VERDICT'))
 except (OSError,ValueError,KeyError,csv.Error) as error:
  row.update(CSV_INTEGRITY='FAIL',PASS=False);row['faults'].append(str(error))
 results.append(row);(a.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n');print(label,'PASS' if row['PASS'] else 'FAIL',flush=True)
print('native trials',sum(r['PASS'] for r in results),'/',len(results),flush=True)
raise SystemExit(0 if results and all(r['PASS'] for r in results) else 2)
