"""短尺EOSのReady通知を反復し、PCM一致と通知待ち時間を別々に判定する。"""
import argparse,json,statistics,subprocess,time
from pathlib import Path
from phase57_study import ROOT,fixture,sha
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=1000);a=p.parse_args();assert 1<=a.repeats<=2000
out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);source=out/'boundary.wav';fixture(source,44100,2,3,'boundary',.25)
check=ROOT/'build/phase58_check';reference=ROOT/'build/phase58_frozen/product_reference';binaries={str(p.relative_to(ROOT)):sha(p) for p in (check,reference)}
(out/'manifest.json').write_text(json.dumps(dict(input_sha256=sha(source),binaries=binaries,repeats=a.repeats,notification_lag_limit_s=1,limit_purpose='Ready通知の60秒取りこぼし検出。音声callback期限やPCM一致の閾値ではない。'),ensure_ascii=False,indent=2)+'\n')
references={}
for speed in (720000,1180000,1580000,1960000):
 for preset in ('candidate','baseline'):
  raw=out/f'{speed}_{preset}.f32';r=subprocess.run(list(map(str,[reference,source,speed,preset,raw])),capture_output=True,text=True,check=True);ref=json.loads(r.stdout);assert sha(raw)==ref['pcm_sha256'];references[(speed,preset)]=(raw,ref)
rows=[]
with (out/'rows.jsonl').open('x') as stream:
 for i in range(a.repeats):
  speed=(720000,1180000,1580000,1960000)[i%4];preset=('candidate','baseline')[(i//4)%2];chunk=(1024,5003)[(i//8)%2];raw,ref=references[(speed,preset)]
  start=time.monotonic();r=subprocess.run(list(map(str,[check,source,speed,preset,raw,ref['output_frames'],ref['pcm_sha256'],chunk])),capture_output=True,text=True,timeout=70);wall=time.monotonic()-start
  d=json.loads(r.stdout) if r.returncode==0 else None
  row=dict(repeat=i+1,speed_micros=speed,preset=preset,chunk=chunk,exit=r.returncode,process_wall_s=wall,result=d,error=r.stderr,pcm_pass=bool(d and d['PASS']),notification_pass=bool(d and 0<=d['ready_notification_lag_s']<1))
  rows.append(row);stream.write(json.dumps(row)+'\n');stream.flush()
  if (i+1)%50==0:
   print(i+1,'PCM',sum(x['pcm_pass'] for x in rows),'wake',sum(x['notification_pass'] for x in rows),flush=True)
   (out/'progress.json').write_text(json.dumps(dict(sessions=i+1,pcm_pass=sum(x['pcm_pass'] for x in rows),notification_pass=sum(x['notification_pass'] for x in rows)),indent=2)+'\n')
for path,digest in binaries.items():assert sha(ROOT/path)==digest
lags=[r['result']['ready_notification_lag_s'] for r in rows if r['result']]
summary=dict(PASS=all(r['pcm_pass'] and r['notification_pass'] for r in rows),sessions=len(rows),pcm_pass=sum(r['pcm_pass'] for r in rows),notification_pass=sum(r['notification_pass'] for r in rows),notification_lag_median_s=statistics.median(lags) if lags else None,notification_lag_max_s=max(lags) if lags else None)
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True);raise SystemExit(0 if summary['PASS'] else 2)
