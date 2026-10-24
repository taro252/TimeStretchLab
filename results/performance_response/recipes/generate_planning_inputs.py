"""C1多event負荷専用。1秒間隔のimpulseをFloat32 mono48kへ格納。品質gateの代替ではない。"""
import argparse,hashlib,json,pathlib,struct,sys
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
rate=48000;amplitude=struct.pack('<f',.72);zero=bytes(65536);rows=[]
def zeros(h,count):
 while count:
  n=min(count,len(zero));h.update(zero[:n]);count-=n
for seconds in [300,600]:
 frames=rate*seconds;size=frames*4
 header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',36+size,b'WAVE',b'fmt ',16,3,1,rate,rate*4,4,32,b'data',size)
 path=o/f'separated_train_{seconds}s.wav';h=hashlib.sha256();h.update(header);cursor=0
 with path.open('xb') as f:
  f.write(header)
  for second in range(seconds):
   at=(second*rate+rate//3)*4;zeros(h,at-cursor);h.update(amplitude);cursor=at+4;f.seek(len(header)+at);f.write(amplitude)
  zeros(h,size-cursor);f.truncate(len(header)+size)
 item=identity(path);assert item['sha256']==h.hexdigest() and item['bytes']==44+size
 rows.append(dict(file=item,physical_allocated_bytes=path.stat().st_blocks*512,seconds=seconds,rate=rate,channels=1,encoding='Float32 little endian',frames=frames,impulses=seconds,interval_input_frames=rate,first_impulse_input_frame=rate//3,amplitude_bytes_le=amplitude.hex(),sparse_storage_only=True))
(o/'MANIFEST.json').write_text(json.dumps(dict(generator=identity(__file__),purpose='C1 planning cost with repeatedly closed events; same logical input in old/new; not quality/AB/RT gate replacement',recipe='canonical 44-byte IEEE Float32 WAV; zeros except .72f at k*48000+16000; 600s PCM exactly 300s PCM repeated twice',inputs=rows),ensure_ascii=False,indent=2)+'\n')
print([(r['file']['sha256'],r['physical_allocated_bytes']) for r in rows])
