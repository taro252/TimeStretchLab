"""Export already-audited actual output, no DSP, resampling, tiling, or listening."""
import argparse,array,hashlib,json,math,pathlib,struct,sys
p=argparse.ArgumentParser();p.add_argument('--base',type=pathlib.Path,required=True);p.add_argument('--build-record',type=pathlib.Path,required=True);a=p.parse_args();b=a.base;build=json.loads(a.build_record.read_text());assert build['status']=='PASS';assert json.loads((b/'ab_final_02/EXPECTED.json').read_text())['source']['sha256']==build['source'];o=b/'current_audition_02';o.mkdir();rows=[]
def ident(p):return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.file_digest(open(p,'rb'),'sha256').hexdigest())
for case in ('A30_fresh','A30_prewarm','A270_fresh','A270_prewarm'):
 cap=b/'ab_final_02'/case;aud=b/'ab_pcm_02'/case/'SUMMARY.json';s=json.loads(aud.read_text());assert s['status']=='PASS' and s['passed']==s['expected']==5
 fmt=json.loads((cap/'SUMMARY.json').read_text());src=cap/'output_before_gain.f32';pcm=array.array('f');pcm.frombytes(src.read_bytes());assert sys.byteorder=='little' and all(math.isfinite(x) for x in pcm)
 for i,x in enumerate(pcm):pcm[i]=x*.5
 data=pcm.tobytes();rate=fmt['source_rate'];ch=fmt['channels'];head=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',36+len(data),b'WAVE',b'fmt ',16,3,ch,rate,rate*ch*4,ch*4,32,b'data',len(data));dest=o/(case+'.wav');dest.write_bytes(head+data);rows.append(dict(case=case,wav=ident(dest),capture_summary=ident(cap/'SUMMARY.json'),pcm_audit=ident(aud),source_output=ident(src),gain=.5,frames=len(pcm)//ch,rate=rate,channels=ch,kind='actual full callback capture, before-gain observer multiplied by fixed gain; no repetition',candidate_source=build['source'],human_listening=None,physical_output=None,RT_approval=False))
(o/'MANIFEST.json').write_text(json.dumps(dict(expected=4,executed=len(rows),rows=rows,purpose='F human audition material; old capture source explicitly bound; does not close F or attest runtime/DAC gain'),indent=2))
