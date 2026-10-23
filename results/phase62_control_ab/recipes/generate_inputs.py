"""MerodoaのWAVFixture.artificialStereoPCM16と同一2秒blockを再現する。"""
import argparse,hashlib,json,math,struct,wave,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--mono-source',type=Path,default=Path('/Users/taro252/Docker/merodoa/build/phase62-native-loop/native-bridge/fixture-48000-1ch.wav'));a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
block=bytearray()
for i in range(96000):
 for hz in (440,660):block.extend(struct.pack('<h',int(f32(f32(.04*math.sin(2*math.pi*hz*i/48000))*f32(32767)))))
rows=[]
expected={240:'5fb7423802baefe17bf5df62e79cd534bb2ad7c41ff4e3a2ae030a8fd4df77e9',300:'94223f409e8db5d44029499f057f81ca7368e2a17a47ba9a7aea3a337050e8c4',10:'82fa50b26925ce290d98609c471c9cf858da8a41511a33fc39937209d5d1a271',12:'d992a233186ff91da5c79eb2d8b8e7c22f158e52423f9bec63eb0b9e266dd5eb'}
for seconds in (240,300,10,12):
 file=a.output/f'artificial_{seconds}s.wav'
 with wave.open(str(file),'wb') as o:o.setnchannels(2);o.setsampwidth(2);o.setframerate(48000);o.writeframes(bytes(block)*(seconds//2))
 sha=hashlib.sha256(file.read_bytes()).hexdigest();assert sha==expected[seconds];rows.append(dict(path=str(file.resolve()),bytes=file.stat().st_size,sha256=sha,rate=48000,channels=2,encoding='PCM16',seconds=seconds))
mono=a.output/'artificial_6s.wav';need='ce21edd20991206d32bef0f45c6025025f90639be37ed8408261961f718bf1c2';assert hashlib.sha256(a.mono_source.read_bytes()).hexdigest()==need, '必須人工mono素材が不一致。別素材へ代用しない';shutil.copy2(a.mono_source,mono);rows.append(dict(path=str(mono.resolve()),sha256=need,restored_from=str(a.mono_source.resolve()),bytes=mono.stat().st_size))
(a.output/'RECIPE.json').write_text(json.dumps(dict(source='MerodoaTests/Support/WAVFixture.swift artificialStereoPCM16',f32_operations=['sample=Float32(.04*sin(2*pi*hz*i/48000))','Int16(sample*Float32(32767)) truncation toward zero'],block_frames=96000,files=rows),indent=2)+'\n')
