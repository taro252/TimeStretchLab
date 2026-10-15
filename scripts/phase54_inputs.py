"""Recreate private repeated float32 test inputs, or verify their exact byte recipe."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
from phase53_sessions import ROOT,wav_pcm
p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
if a.output:a.output.mkdir(parents=True,exist_ok=False)
sources={r['path']:r for r in json.loads((ROOT/'results/phase54/source_manifest.json').read_text())}
rows=json.loads((ROOT/'results/phase54/input_manifest.json').read_text());passed=0
for row in rows:
 source=ROOT/row['source'];raw=source.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=sources[row['source']]['sha256']:raise SystemExit('Private source hash mismatch: '+str(source))
 pcm,ch,n=wav_pcm(source);length=row['seconds']*row['rate']*ch*4
 header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',36+length,b'WAVE',b'fmt ',16,3,ch,row['rate'],row['rate']*ch*4,ch*4,32,b'data',length)
 digest=hashlib.sha256();digest.update(header);stream=(a.output/Path(row['path']).name).open('xb') if a.output else None
 try:
  if stream:stream.write(header)
  remaining=length
  while remaining:
   block=pcm[:min(remaining,len(pcm))];digest.update(block)
   if stream:stream.write(block)
   remaining-=len(block)
 finally:
  if stream:stream.close()
 if digest.hexdigest()!=row['sha256']:raise SystemExit('Repeated recipe hash mismatch: '+row['path'])
 passed+=1
print('private input byte recipe',passed,'/',len(rows),'PASS')
