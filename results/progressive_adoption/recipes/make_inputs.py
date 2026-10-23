#!/usr/bin/env python3
"""Derive 16s Float32 fixtures without decoding, quantization or resampling."""
import argparse,hashlib,json,pathlib,struct
p=argparse.ArgumentParser();p.add_argument('--source-root',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
items=[('mono48','results/phase56/long/chain_300s.wav','13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'),('stereo441','build/phase61_fast_seek/music_300s.wav','fc8be98125b35e0b2bde0728ef8ccfc60ab2aee4462b72f61c55733ae277cf58')];rows=[]
for name,rel,digest in items:
 source=a.source_root/rel;data=source.read_bytes();assert hashlib.sha256(data).hexdigest()==digest
 fmt=pcm=None;pos=12
 while pos+8<=len(data):
  tag,n=struct.unpack_from('<4sI',data,pos);pos+=8
  if tag==b'fmt ':fmt=data[pos:pos+n]
  if tag==b'data':pcm=data[pos:pos+n]
  pos+=n+n%2
 assert fmt and pcm
 code,ch,rate,_,align,bits=struct.unpack_from('<HHIIHH',fmt);assert code==3 and bits==32 and align==ch*4
 n=16*rate;body=pcm[:n*align];assert len(body)==n*align
 content=b'fmt '+struct.pack('<I',len(fmt))+fmt+(b'\0' if len(fmt)%2 else b'')+b'data'+struct.pack('<I',len(body))+body
 target=a.output/(name+'_16s.wav');target.write_bytes(b'RIFF'+struct.pack('<I',len(content)+4)+b'WAVE'+content)
 rows.append({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'source':str(source),'source_sha256':digest,'source_frames':300*rate,'frames':n,'channels':ch,'rate':rate,'encoding':'Float32','method':'verbatim prefix PCM and original fmt; RIFF sizes rewritten','bytes':target.stat().st_size})
(a.output/'MANIFEST.json').write_text(json.dumps({'schema':'adoption-inputs-v1','inputs':rows},indent=2)+'\n');print(json.dumps(rows))
