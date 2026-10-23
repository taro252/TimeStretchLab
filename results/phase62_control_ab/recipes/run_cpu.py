"""Native-only CPU: plain30秒×3と別の寄与試行。UI/Swiftを含まない。"""
import argparse,json,subprocess,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);record=json.loads(a.build_record.read_text());assert record['status']=='PASS';binary=Path(record['binaries']['phase62_control_cpu_native']['path']);assert identity(binary)==record['binaries'][binary.name];jobs=[dict(id='plain',mode='costs-off',scope='full',expected=8,required_ids=['unprepared','off1','off2','off3','loop2s','loop30s','paused','stopped']),dict(id='attribution',mode='costs-on',scope='short',expected=2,required_ids=['off1','paused'])]
for j in jobs:j['command']=[str(binary),str(a.input.resolve()),j['mode'],j['scope'],str(out/j['id']),record['source']]
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
save(out/'EXPECTED.json',dict(expected_programs=2,expected_windows=10,jobs=jobs,build_record=identity(a.build_record),input=identity(a.input),binary=identity(binary),source=record['source'],driver=identity(Path(__file__)),UI_included=False,serial_audio=True));rows=[]
for j in jobs:
 start=time.monotonic();timed=False
 with (out/(j['id']+'.log')).open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=420).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 folder=out/j['id'];r=json.loads((folder/'SUMMARY.json').read_text()) if (folder/'SUMMARY.json').exists() else {};measure=[json.loads(x) for x in (folder/'measurements.jsonl').read_text().splitlines()] if (folder/'measurements.jsonl').exists() else [];ok=code==0 and not timed and r.get('status')=='PASS' and r.get('run_complete') is True and r.get('executed')==r.get('expected')==j['expected']==len(measure) and [x['id'] for x in measure]==j['required_ids']
 rows.append(dict(id=j['id'],status='PASS' if ok else 'FAIL',exit=code,timeout=timed,seconds=time.monotonic()-start,summary=r,measurements=measure));save(out/'SUMMARY.json',dict(status='PASS' if len(rows)==2 and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',run_complete=len(rows)==2,rows=rows));print(j['id'],rows[-1]['status'],round(rows[-1]['seconds'],2),flush=True)
 if not ok:raise SystemExit(2)
