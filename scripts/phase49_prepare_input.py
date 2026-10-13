#!/usr/bin/env python3
"""Copy a bounded input section without resampling or changing PCM bytes."""
import struct
from pathlib import Path
def clip(source,target,seconds):
    source=Path(source);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as f:
        assert f.read(4)==b'RIFF';f.read(4);assert f.read(4)==b'WAVE'
        fmt=None;data_offset=None;data_size=0
        while True:
            header=f.read(8)
            if len(header)!=8:break
            name,size=struct.unpack('<4sI',header)
            if name==b'fmt ':fmt=f.read(size)
            elif name==b'data':data_offset=f.tell();data_size=size;f.seek(size,1)
            else:f.seek(size,1)
            if size%2:f.seek(1,1)
        assert fmt is not None and data_offset is not None
        code,channels,rate,byte_rate,align,bits=struct.unpack('<HHIIHH',fmt[:16])
        assert code in (1,3)
        length=round(seconds*rate)*align;assert length<=data_size
        f.seek(data_offset)
        with target.open('xb') as out:
            out.write(struct.pack('<4sI4s',b'RIFF',4+8+len(fmt)+(len(fmt)%2)+8+length,b'WAVE'))
            out.write(struct.pack('<4sI',b'fmt ',len(fmt))+fmt)
            if len(fmt)%2:out.write(b'\0')
            out.write(struct.pack('<4sI',b'data',length))
            remaining=length
            while remaining:
                chunk=f.read(min(remaining,1024*1024));assert chunk
                out.write(chunk);remaining-=len(chunk)
    return dict(rate=rate,channels=channels,frames=length//align,format=code,bits=bits)
if __name__=='__main__':
    print(clip('results/phase40/long_input/drums_repeat_180.wav','results/phase49/input/drums30.wav',30))
