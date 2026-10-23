#!/usr/bin/env python3
"""Isolated attribution of unused Phase57 stage hashes. Product is untouched."""
import argparse,hashlib,json,pathlib
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
core=a.source/'src/prototype/Phase36SynthesisCore.h';synthesis=a.source/'src/prototype/Phase57ProgressiveSynthesis.cpp'
s=core.read_text();assert s.count('int pinnedFd=-1)')==1;s=s.replace('int pinnedFd=-1)','int pinnedFd=-1,bool recordDigests=true)')
s=s.replace('digests_(digests), resolutionIndex_', 'digests_(recordDigests?&digests:nullptr), resolutionIndex_')
s=s.replace('Phase13StageDigests& digests_;','Phase13StageDigests* digests_;')
s=s.replace('digests_.','digests_->')
s=s.replace('        hashSpectrum(digests_->fft','        if(digests_)hashSpectrum(digests_->fft')
s=s.replace('            hashSpectrum(digests_->phase','            if(digests_)hashSpectrum(digests_->phase')
s=s.replace('            for (const auto sample : synthesized_) hashFloat','            if(digests_)for (const auto sample : synthesized_) hashFloat')
s=s.replace('            hashFloat(digests_->ola','            if(digests_)hashFloat(digests_->ola')
s=s.replace('if (stageTrace_ && std::llabs','if (stageTrace_ && digests_ && std::llabs')
p=a.output/'prototype/Phase36SynthesisCore.h';p.parent.mkdir();p.write_text(s)
s=synthesis.read_text();needle='false,pinnedBytes,pinnedFd);';assert s.count(needle)==1;s=s.replace(needle,'false,pinnedBytes,pinnedFd,false);')
s=s.replace('            hashFloat(digests.lowFir,lf);hashFloat(digests.highFir,hf);','            // Offline attribution: unused stage digests omitted.')
s=s.replace('pcm[c][i]=value;hashFloat(digests.fir,value);','pcm[c][i]=value;')
(a.output/'Phase57NoDigests.cpp').write_text(s)
meta={'schema':'unused-phase57-digest-experiment-v1','product_changed':False,'arithmetic_changed':False,'oracle_rebuilt':False,'input_sources':{str(x.relative_to(a.source)):hashlib.sha256(x.read_bytes()).hexdigest() for x in (core,synthesis)},'generated':{str(x.relative_to(a.output)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(a.output.rglob('*')) if x.is_file()},'acceptance':'all compared PCM bits identical; positive CPU contribution before production; RT deadlines not relaxed'}
(a.output/'MANIFEST.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta))
