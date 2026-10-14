"""Read-only, all-session PCM/CSV gate shared by normal and correction paths."""
import csv, hashlib, io, json, math, struct, subprocess
from pathlib import Path
from phase47_evidence import read_csv
from phase52_verdict import finalize
ROOT=Path(__file__).resolve().parents[1]
CSV_COLUMNS={
 'callbacks.csv':'sequence,epoch,start_ns,end_ns,io_end_ns,host_ns,sample_time,flags,requested,wanted,received,output,generation,fifo_before,last_publication_ns',
 'workers.csv':'cycle,start_ns,published_ns,frames,fifo_after,wall_s,cpu_s,dsp_wall_s,dsp_cpu_s,fifo_wait_s,write_s,mutex_wait_s,mutex_hold_s,plan_wall_s,publication_interval_s',
 'plans.csv':'generation,requested_output,requested_input,from,target,fence,prepared,published,applied_frame,applied_output,completion_output,density_input,map_bytes,plan_ms,state_preserved',
 'operations.csv':'id,session,generation,observed_ns,sent_ns,completed_ns,target,status,apply_output,complete_output',
}
TERMINAL_OPERATIONS={'Completed','Replaced','Duplicate','Rejected','Cancelled','Configured'}
DENSITY_CONVERSION_REASON='Replay density_input converted from Mid frame units to input samples (factor 1024); no other field or native evidence changed.'


def validate_plans(path,row,operations,legacy=False):
 """Validate the saved original as well as any separately corrected replay."""
 path=Path(path);faults=[];rows=[];digest=None
 try:
  data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
  columns=CSV_COLUMNS['plans.csv'].split(',')
  rows,validated_digest=read_csv(path,set(columns))
  if digest!=validated_digest:raise ValueError('plan_changed_during_validation')
  if next(csv.reader(io.StringIO(data.decode('utf-8')),strict=True))!=columns:
   faults.append('plan_header_order_or_columns')
  for record in rows:
   for key,value in record.items():
    number=float(value)
    if not math.isfinite(number) or number<0:raise ValueError('invalid_plan_value:'+key)
    if key not in ('from','target','plan_ms'):int(value)
   if not .4<=float(record['from'])<=2 or not .4<=float(record['target'])<=2:
    faults.append('plan_speed_range')
  generations=[int(record['generation']) for record in rows]
  if any(g<=0 for g in generations) or generations!=sorted(set(generations)):
   faults.append('plan_generation_order_or_duplicate')
  current=[op for op in operations if op['session']==row.get('session')]
  known={int(op['generation']):op for op in current if int(op['generation'])>0}
  # Rejected requests can leave legitimate generation gaps. Every completed
  # operation must still have its own replay row, including legacy captures.
  required={int(op['generation']) for op in current if op['status']=='Completed' or
            (op['status']=='Cancelled' and int(op['apply_output'])>0)}
  if not set(generations).issubset(known) or not required.issubset(generations):
   faults.append('session_plan_generation_missing_or_unknown')
  for record in rows:
   op=known.get(int(record['generation']))
   if op and (float(op['target'])!=float(record['target']) or op['status']=='Rejected'):
    faults.append('plan_operation_target_or_status')
   if op and op['status']=='Completed' and (int(op['apply_output'])!=int(record['applied_output']) or
       int(op['complete_output'])!=int(record['completion_output'])):
    faults.append('plan_operation_output_positions')
  if 'plan_rows' in row:
   if len(rows)!=int(row['plan_rows']):faults.append('plan_row_count')
  elif not legacy:faults.append('plan_row_count_missing')
  elif any(op['status']=='Cancelled' and int(op['generation'])>0 and int(op['apply_output'])==0 for op in current):
   faults.append('legacy_cancelled_plan_count_unverifiable')
 except (OSError,ValueError,UnicodeError,csv.Error,KeyError,TypeError,StopIteration) as error:
  faults.append(str(error))
 return dict(CSV_INTEGRITY='FAIL' if faults else 'PASS',faults=faults,
             sha256=digest,rows=len(rows),path=str(path),
             row_count_basis='captured_plan_rows' if 'plan_rows' in row else 'legacy_operation_generations'),rows


def convert_density_units(source,destination,row,operations,legacy=False):
 """The only permitted correction; refuse to normalize an invalid original."""
 audit,rows=validate_plans(source,row,operations,legacy)
 if audit['CSV_INTEGRITY']!='PASS':raise ValueError('Invalid original plans.csv: '+str(audit['faults']))
 with Path(destination).open('x',newline='') as stream:
  writer=csv.DictWriter(stream,fieldnames=CSV_COLUMNS['plans.csv'].split(','),lineterminator='\n')
  writer.writeheader()
  for record in rows:writer.writerow(dict(record,density_input=str(int(record['density_input'])*1024)))


def validate_operations(operations,row):
 """History is emitted in completion order; IDs are globally sequential."""
 faults=[]
 try:
  if row['reason'] not in ('EOS','User','RouteChanged','WorkerError'):faults.append('unknown_session_end_reason')
  if row['reason']=='EOS' and (row['state']!='Ended' or row['eos']!='1'):faults.append('operation_eos_state')
  if row['reason'] in ('User','RouteChanged') and (row['state']!='Stopped' or row['eos']!='0'):
   faults.append('operation_stop_state')
  ids=[int(op['id']) for op in operations]
  if sorted(ids)!=list(range(1,len(ids)+1)):faults.append('operation_id_gap_or_duplicate')
  pairs=[];current_session=int(row.get('session',0))
  for op in operations:
   status=op['status'];session=int(op['session']);generation=int(op['generation'])
   if status not in TERMINAL_OPERATIONS:faults.append('nonterminal_or_unknown_operation:'+status)
   if not 1<=session<=current_session:faults.append('operation_session')
   if generation<0:faults.append('operation_generation')
   if generation:
    pairs.append((session,generation))
    if int(op['sent_ns'])<=0:faults.append('operation_generation_unsent')
   if status=='Completed' and (generation==0 or int(op['completed_ns'])<int(op['sent_ns']) or
       int(op['complete_output'])<int(op['apply_output'])):faults.append('completed_operation_metadata')
   if status in ('Replaced','Duplicate','Configured') and generation!=0:
    faults.append('unsubmitted_operation_generation')
  if len(set(pairs))!=len(pairs):faults.append('operation_generation_duplicate')
  for session in {int(op['session']) for op in operations}:
   generations=[int(op['generation']) for op in sorted(operations,key=lambda op:int(op['id']))
                if int(op['session'])==session and int(op['generation'])>0]
   if generations!=list(range(1,len(generations)+1)):faults.append('operation_generation_gap_or_order')
 except (ValueError,KeyError,TypeError) as error:faults.append('operation_metadata:'+str(error))
 return faults


def kv(path):
 return dict(line.split('=',1) for line in Path(path).read_text().splitlines() if '=' in line)
def wav_pcm(path):
 data=Path(path).read_bytes()
 if data[:4]!=b'RIFF' or data[8:12]!=b'WAVE':raise ValueError('RIFF/WAVE required')
 fmt=None;pcm=None;at=12
 while at+8<=len(data):
  tag,n=struct.unpack_from('<4sI',data,at);body=data[at+8:at+8+n];at+=8+n+(n%2)
  if len(body)!=n:raise ValueError('truncated WAV')
  if tag==b'fmt ':fmt=struct.unpack_from('<HHIIHH',body)
  if tag==b'data':pcm=body
 if fmt is None or pcm is None or fmt[0]!=3 or fmt[5]!=32:raise ValueError('float32 reference required')
 if len(pcm)%fmt[4]:raise ValueError('partial PCM frame')
 return pcm,fmt[1],len(pcm)//fmt[4]

def integrity(folder,row,legacy=False,plan_path=None,correction_reason=None):
 faults=[];tables={};files={};folder=Path(folder)
 required={name:set(columns.split(',')) for name,columns in CSV_COLUMNS.items()}
 for name,columns in required.items():
  if name=='plans.csv':continue
  try:
   rows,digest=read_csv(folder/name,columns)
   tables[name]=rows;files[name]={'rows':len(rows),'sha256':digest}
  except (OSError,ValueError,UnicodeError,csv.Error) as e:faults.append(name+':'+str(e))
 ops=tables.get('operations.csv',[])
 if legacy and 'session' not in row:
  ids={r['session'] for r in ops}
  if len(ids)==1:row['session']=next(iter(ids));row['legacy_session_id_source']='saved_operations.csv'
  elif ids:faults.append('legacy_session_id_ambiguous')
 # Always inspect the untouched original before opening a corrected replay.
 original,plans=validate_plans(folder/'plans.csv',row,ops,legacy)
 plan_csv={'original':original};tables['plans.csv']=plans;files['plans.csv']=original
 faults+=['original_plans:'+fault for fault in original['faults']]
 if plan_path and Path(plan_path)!=folder/'plans.csv':
  corrected,converted=validate_plans(plan_path,row,ops,legacy)
  plan_csv['corrected']=corrected;files['plans_samples.csv']=corrected
  faults+=['corrected_plans:'+fault for fault in corrected['faults']]
  permitted=bool(correction_reason) and original['CSV_INTEGRITY']==corrected['CSV_INTEGRITY']=='PASS' and len(plans)==len(converted)
  if permitted:
   permitted=all(all(b[key]==a[key] for key in a if key!='density_input') and
                 b['density_input']==str(int(a['density_input'])*1024) for a,b in zip(plans,converted))
  plan_csv['conversion']={'reason':correction_reason,'field':'density_input','factor':1024,
                         'original_sha256':original['sha256'],'corrected_sha256':corrected['sha256'],
                         'PERMITTED_CONVERSION':'PASS' if permitted else 'FAIL'}
  if not permitted:faults.append('unauthorized_or_unverifiable_plan_conversion')
 try:
  cb=tables.get('callbacks.csv',[]);workers=tables.get('workers.csv',[]);ops=tables.get('operations.csv',[])
  for name,rows in tables.items():
   for r in rows:
    for key,value in r.items():
     if key=='status':continue
     x=float(value)
     if not math.isfinite(x):raise ValueError(name+': nonfinite '+key)
     if x<0 and not (name=='workers.csv' and key=='publication_interval_s' and r is rows[0] and x==-1):
      raise ValueError(name+': unexpected negative '+key)
  if [int(r['sequence']) for r in cb]!=list(range(1,len(cb)+1)):faults.append('callback_sequence')
  if len(cb)!=int(row['callback_calls']):faults.append('callback_count')
  cursor=presented=0
  for r in cb:
   n=int(r['received']);wanted=int(r['wanted'])
   if n>wanted or (wanted and int(r['output'])!=cursor):faults.append('callback_pcm_cursor')
   cursor+=n;presented+=wanted
  if cursor!=int(row['consumed_frames']) or presented!=int(row['presented_frames']):faults.append('callback_frames')
  if [int(r['cycle']) for r in workers]!=list(range(1,len(workers)+1)):faults.append('worker_sequence')
  if sum(int(r['frames']) for r in workers)!=int(row['produced_frames']):faults.append('worker_publication_frames')
  faults+=validate_operations(ops,row)
  if not legacy:
   for key in ('worker_error','native_error','concurrent_renders','channels','preset','session','generated_frames','published_frames','device_raw_frames','hash_scope','hash_frames','start_state'):
    if key not in row:faults.append('required_metadata:'+key)
   for field,name in [('callback_rows','callbacks.csv'),('worker_rows','workers.csv'),('plan_rows','plans.csv'),('operation_rows','operations.csv')]:
    if int(row[field])!=len(tables.get(name,[])):faults.append(field)
   if row['hash_scope']!='fifo_published_raw_float32_interleaved_prefix' or int(row['hash_frames'])!=int(row['published_frames']):faults.append('hash_scope')
   if int(row['generated_frames'])<int(row['published_frames']) or int(row['published_frames'])!=int(row['produced_frames']) or int(row['device_raw_frames'])!=int(row['consumed_frames']):faults.append('generated_published_consumed_scope')
   if not (0<=int(row['consumed_frames'])<=int(row['published_frames'])<=int(row['generated_frames'])):faults.append('frame_scope_order')
   if 'fifo_frames' in row and (int(row['fifo_frames'])!=16384 or int(row['lead_frames'])!=(16384 if row['preset']=='candidate' else 12288) or int(row['block_frames'])!=2048 or row['qos']!='inherited'):faults.append('session_dsp_configuration')
   if row['start_state']!='Playing' or row['preset'] not in ('candidate','baseline'):faults.append('session_configuration')
   if not .4<=float(row['initial'])<=2: faults.append('initial_speed')
 except (ValueError,KeyError,TypeError) as e:faults.append('capture_metadata:'+str(e))
 return {'CSV_INTEGRITY':'FAIL' if faults else 'PASS','faults':faults,'files':files,
         'plan_csv':plan_csv},tables

def verify_run(folder,input_path,exit_code,reference_dir=None,legacy=False,reference_override=None,plan_override=None,original=None,correction_reason=None):
 folder=Path(folder);manifest_faults=[]
 try:
  if (folder/'sessions.csv').exists():
   manifest,_=read_csv(folder/'sessions.csv',{'session','folder'})
   ids=[r['session'] for r in manifest]
   if len(ids)!=len(set(ids)) or [int(i) for i in ids]!=sorted(int(i) for i in ids):manifest_faults.append('session_ids')
   if [r['folder'] for r in manifest].count('.')!=1 or manifest[-1]['folder']!='.':manifest_faults.append('final_session')
   actual={p.name for p in folder.glob('closed_session_*') if p.is_dir()}
   if actual!={r['folder'] for r in manifest if r['folder']!='.'}:manifest_faults.append('session_inventory')
  elif legacy:manifest=[{'folder':p.name} for p in sorted(folder.glob('closed_session_*'))]+[{'folder':'.'}]
  else:manifest_faults.append('sessions_manifest_missing');manifest=[{'folder':'.'}]
 except (OSError,ValueError,csv.Error,IndexError):manifest_faults.append('sessions_manifest_invalid');manifest=[{'folder':'.'}]
 sessions=[]
 for entry in manifest:
  name=entry['folder']
  if name!='.' and (Path(name).name!=name or not name.startswith('closed_session_')):
   manifest_faults.append('unsafe_session_path');continue
  path=folder/name
  evidence=None;row={}
  try:
   row=kv(path/'summary.txt')
   saved=next((s for s in (original or {}).get('sessions',[]) if s.get('folder')==name),{})
   if name=='.':saved=dict(saved,**{k:original[k] for k in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','CSV_INTEGRITY') if original and k in original})
   for key in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','CSV_INTEGRITY'):
    if saved.get(key)=='FAIL':row[key]='FAIL'
   if name!='.' and entry.get('session') and name!='closed_session_'+entry['session']:manifest_faults.append('session_folder_id')
   if entry.get('session') and entry['session']!=row['session']:manifest_faults.append('session_id_mismatch')
   plan=Path(plan_override) if name=='.' and plan_override else path/'plans.csv'
   evidence,tables=integrity(path,row,legacy,plan,correction_reason)
   remaining=0
   if name=='.':
    try:
     life=kv(folder/'lifecycle.txt');remaining=int(life['remaining_actions'])
     read_csv(folder/'actions.csv',{'planned_seconds','type','result'})
     if not legacy and int(life['restarts'])!=len(manifest)-1:evidence['faults'].append('restart_session_inventory')
    except (OSError,ValueError,KeyError,csv.Error):evidence['faults'].append('lifecycle_or_actions_missing_invalid')
   if manifest_faults:evidence['faults']+=manifest_faults
   if evidence['faults']:evidence['CSV_INTEGRITY']='FAIL'
   ref=Path(reference_override[name]) if isinstance(reference_override,dict) and name in reference_override else Path(reference_override) if name=='.' and reference_override and not isinstance(reference_override,dict) else None
   if ref is None:
    if evidence['CSV_INTEGRITY']!='PASS':raise ValueError('Invalid CSV evidence; refusing reference replay')
    if reference_dir is None:raise ValueError('reference location required')
    ref=Path(reference_dir)/('final.wav' if name=='.' else name+'.wav')
    if ref.exists():raise ValueError('Refusing to overwrite reference evidence')
    ref.parent.mkdir(parents=True,exist_ok=True)
    r=subprocess.run(list(map(str,[ROOT/'build/playback_reference',input_path,ref,row['initial'],plan,'L2' if row['preset']=='candidate' else 'C','safe-density'])),capture_output=True,text=True,timeout=240)
    ref.with_suffix('.log').write_text(r.stdout+r.stderr)
    if r.returncode:raise ValueError('reference replay failed: '+r.stderr)
   pcm,ch,total=wav_pcm(ref);frames=int(row['produced_frames'])
   digest=hashlib.sha256(pcm[:frames*ch*4]).hexdigest()
   match=frames<=total and digest==row['raw_pcm_sha256']
   if row['reason']=='EOS':match&=frames==total and int(row['output_frames'])==total
   if not legacy:match&=ch==int(row['channels'])
   row['PCM_CORRECTNESS']='PASS' if match else 'FAIL'
   row['reference_pcm']={'frames':total,'compared_frames':frames,'channels':ch,'sha256':digest,'scope':'FIFO published prefix [0, produced_frames)'}
   if name=='.' and original:
    for key in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','CSV_INTEGRITY'):
     if original.get(key)=='FAIL':row[key]='FAIL'
   if name=='.' and original and original.get('PCM_CORRECTNESS')=='FAIL' and not correction_reason:row['PCM_CORRECTNESS']='FAIL'
   correction=None
   if name=='.' and correction_reason:
    correction={'reason':correction_reason,'before':{'PCM_CORRECTNESS':(original or {}).get('PCM_CORRECTNESS','UNKNOWN')},'after':{'PCM_CORRECTNESS':row['PCM_CORRECTNESS'],'reference_sha256':hashlib.sha256(ref.read_bytes()).hexdigest()}}
   result=finalize(row,0,[{'VERDICT':'PASS'}],evidence,expected_route=row['reason']=='RouteChanged',expected_stop=row['reason']=='User',remaining_actions=remaining,pcm_correction=correction)
   # A process exit belongs to the whole run, not a prior stopped session.
   result['folder']=name;sessions.append(result)
  except (OSError,ValueError,KeyError,subprocess.SubprocessError) as e:
   evidence=evidence or {'CSV_INTEGRITY':'FAIL','faults':['session_unverifiable:'+str(e)]}
   row.update(PCM_CORRECTNESS='INDETERMINATE',MEASUREMENT_QUALITY='FAIL')
   result=finalize(row,0,[],evidence)
   result.update(folder=name,error=str(e));sessions.append(result)
 final=next((s for s in sessions if s['folder']=='.'),{})
 evidence=final.get('evidence',{'CSV_INTEGRITY':'FAIL','faults':['final_session_unverifiable']})
 result=finalize(final,exit_code,sessions,evidence,expected_route=final.get('reason')=='RouteChanged',expected_stop=final.get('reason')=='User')
 if manifest_faults:result['VERDICT']='FAIL'
 result['manifest_faults']=manifest_faults
 return result
