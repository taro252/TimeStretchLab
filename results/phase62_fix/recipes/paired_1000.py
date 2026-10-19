"""arm64旧版・新版を同じ入力・出力装置ID/レート/バッファで直列比較。"""
import json,sys,time,subprocess,ctypes
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
F=ROOT/'build/phase62_fix/run_01/final_v9';OUT=F/'paired_1000';INPUT=ROOT/'build/phase62/run_01/native_release/boundary_48000_2_1.wav';OLD=ROOT/'build/phase62_fix/run_01/baseline_release/phase62_native_tests';NEW=F/'release/phase62_native_tests'
def device():
 class P(ctypes.Structure):_fields_=[('selector',ctypes.c_uint32),('scope',ctypes.c_uint32),('element',ctypes.c_uint32)]
 audio=ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio');four=lambda x:int.from_bytes(x.encode(),'big')
 def get(obj,prop,kind):
  address=P(four(prop),four('glob'),0);value=kind();size=ctypes.c_uint32(ctypes.sizeof(value));status=audio.AudioObjectGetPropertyData(obj,ctypes.byref(address),0,None,ctypes.byref(size),ctypes.byref(value))
  if status:raise RuntimeError(str(status)+' '+prop)
  return value.value
 obj=get(1,'dOut',ctypes.c_uint32);return dict(device_id=obj,rate=get(obj,'nsrt',ctypes.c_double),buffer_frames=get(obj,'fsiz',ctypes.c_uint32))
if len(sys.argv)>1:
 name=sys.argv[1]
 if name=='compare':
  old=json.loads((OUT/'old/result.json').read_text());new=json.loads((OUT/'new/result.json').read_text());beforeAfter=[json.loads((OUT/(n+'_device.json')).read_text()) for n in ('old','new')];snapshots=[v[key] for v in beforeAfter for key in ('before','after')]
  fields=('rate','channels','speed','range_seconds','preset','mode','cycles','device_rate','device_buffer');same=all(old[k]==new[k] for k in fields)
  a=json.loads((OUT/'old/last_boundary.json').read_text());b=json.loads((OUT/'new/last_boundary.json').read_text());same &= a['input_a']==b['input_a'] and a['input_b_exclusive']==b['input_b_exclusive']
  same &= all(v==snapshots[0] for v in snapshots) and all(v['rate']==48000 and v['buffer_frames']==512 for v in snapshots)
  result=dict(PASS=bool(same),same_conditions=bool(same),conditions={k:old[k] for k in fields},input=identity(INPUT),old=old,new=new,old_cpu_percent=100*old['process_cpu_s']/old['wall_s'],new_cpu_percent=100*new['process_cpu_s']/new['wall_s'],cpu_seconds_reduction_percent=100*(1-new['process_cpu_s']/old['process_cpu_s']),device_snapshots=snapshots,order=['old','new'],replicates=1,period_contract=dict(old='L-N temporal overlap',new='L, no temporal overlap'))
  (OUT/'PAIR_COMPARISON.json').write_text(json.dumps(result,indent=2)+'\n');raise SystemExit(int(not result['PASS']))
 before=device()
 if before['rate']!=48000 or before['buffer_frames']!=512:raise SystemExit('条件48kHz/512が未成立')
 host=OLD if name=='old' else NEW;command=[str(host),str(INPUT),str(OUT/name),'.5','2','1000','candidate','normal'];p=subprocess.run(command);after=device()
 (OUT/(name+'_device.json')).write_text(json.dumps(dict(PASS=before==after,before=before,after=after,command=command,host=identity(host)),indent=2)+'\n');raise SystemExit(p.returncode if p.returncode else int(before!=after))
cases=[dict(id='architecture',kind='exit')]
for name in ('old','new'):cases.append(dict(id=name,kind='native',cycles=1000,period_preserving=name=='new',required=[name+'/result.json',name+'/boundaries.jsonl',name+'/last_boundary.json',name+'_device.json'],result=name+'/result.json'))
cases.append(dict(id='same_conditions',kind='json_pass',required=['PAIR_COMPARISON.json'],result='PAIR_COMPARISON.json'))
frozen=source_manifest(ROOT);ledger=Ledger(OUT,cases,dict(source=frozen,driver=identity(__file__),old_binary=identity(OLD),old_source=json.loads((ROOT/'build/phase62_fix/run_01/START_STATE.json').read_text()),architecture='arm64',configuration='Release',input=identity(INPUT)))
while not (F/'exact_finite/SUMMARY.json').is_file():time.sleep(5)
if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise SystemExit('SOURCE CHANGED')
for name in ('architecture','old','new','same_conditions'):
 command=[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py',OLD,NEW] if name=='architecture' else [sys.executable,'-B',__file__,'compare' if name=='same_conditions' else name]
 ok=ledger.run(name,command,cwd=ROOT,timeout=900,inputs=[INPUT,OLD,NEW]);print(name,ledger.rows[name]['status'],flush=True)
 if name=='architecture' and not ok:break
ledger.save();r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
