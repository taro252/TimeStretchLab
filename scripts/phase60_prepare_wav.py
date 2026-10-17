"""Float32拡張WAVのdataを変えず、対応RIFF/IEEE_FLOAT fmt16へ包み直す。"""
import argparse,hashlib,json,struct
from pathlib import Path
def rewrap(source,destination):
    data=source.read_bytes();assert data[:4]==b'RIFF' and data[8:12]==b'WAVE'
    at=12;fmt=payload=None
    while at+8<=len(data):
        kind,n=struct.unpack_from('<4sI',data,at);chunk=data[at+8:at+8+n]
        if len(chunk)!=n:raise ValueError('Truncated RIFF')
        if kind==b'fmt ':fmt=chunk
        if kind==b'data':payload=chunk
        at+=8+n+(n&1)
    if fmt is None or payload is None:raise ValueError('Missing fmt/data')
    tag,ch,rate,byte_rate,align,bits=struct.unpack_from('<HHIIHH',fmt)
    if tag!=0xfffe or len(fmt)<40 or fmt[24:40]!=bytes.fromhex('0300000000001000800000aa00389b71') or bits!=32 or ch not in (1,2) or rate not in (44100,48000) or align!=ch*4 or byte_rate!=rate*align or len(payload)%align:raise ValueError('Requires supported Float32 extensible WAV')
    if struct.unpack_from('<H',fmt,18)[0]!=32 or struct.unpack_from('<I',fmt,20)[0] not in (0,3 if ch==2 else 4):raise ValueError('Unsupported valid bits/channel layout')
    header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',36+len(payload),b'WAVE',b'fmt ',16,3,ch,rate,byte_rate,align,bits,b'data',len(payload))
    with destination.open('xb') as f:f.write(header);f.write(payload)
    return {'source_sha256':hashlib.sha256(data).hexdigest(),'wav_sha256':hashlib.sha256(header+payload).hexdigest(),'pcm_payload_sha256':hashlib.sha256(payload).hexdigest(),'pcm_payload_unchanged':True,'frames':len(payload)//align,'channels':ch,'sample_rate':rate}
if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('source',type=Path);p.add_argument('destination',type=Path);a=p.parse_args();print(json.dumps(rewrap(a.source,a.destination),indent=2))
