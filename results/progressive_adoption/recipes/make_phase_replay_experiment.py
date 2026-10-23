#!/usr/bin/env python3
"""Generate an explicitly offline, non-product local-v2 experiment.

The frozen oracle is NEVER rebuilt. Exact product sources are not modified.
The experiment replays the original FFT/phase sequence from zero up to the
local seed, skipping only IFFT/OLA in that prefix. This is O(prefix), so passing
quality alone cannot approve Interactive latency or cold AB performance.
"""
import argparse,hashlib,json,pathlib
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
core=a.source/'src/prototype/Phase36SynthesisCore.h'
synthesis=a.source/'src/prototype/Phase57ProgressiveSynthesis.cpp'
study=a.source/'src/prototype/Phase61FastSeekStudy.cpp'
original={str(x.relative_to(a.source)):hashlib.sha256(x.read_bytes()).hexdigest() for x in (core,synthesis,study)}
s=core.read_text()
assert s.count('    void processFrame() {')==1
s=s.replace('    void processFrame() {','    void processFrame(bool synthesizeOutput=true) {')
needle='        for (std::size_t c=0; c<reader_.channels(); ++c) {\n            StageClock synthesisMeasure(profile_,3,resolutionIndex_);'
assert s.count(needle)==1
s=s.replace(needle,needle.replace('for (std::size_t','if(synthesizeOutput) for (std::size_t'))
needle='    void copyRuntimeStateFrom(const ResolutionStream& other){'
method="""    void initializePhaseReplayedAt(std::size_t input,std::size_t output){
        const auto step=hop_/(config_.timeRatio>2?2:1);
        if(nextFrame_||produced_||position_||input%step||!modeChanges_.empty()||tracker_||resynchronizer_||stageTrace_)
            throw std::invalid_argument("Invalid phase replay context");
        const auto start=std::llround(detection_.position(double(input)));
        if(start<0||std::size_t(start)>output)throw std::invalid_argument("Phase replay OLA origin after output");
        // Preserve the original per-band hop, event midpoint, phase locking,
        // stereo coherence and arithmetic sequence. No absolute clock formula.
        while(position_<input)processFrame(false);
        if(position_!=input)throw std::logic_error("Phase replay missed common input lattice");
        produced_=std::size_t(start);
        for(auto& ola:olas_)ola.resetAt(produced_);
    }
"""
assert s.count(needle)==1;s=s.replace(needle,method+needle)
path=a.output/'prototype/Phase36SynthesisCore.h';path.parent.mkdir();path.write_text(s)
s=synthesis.read_text();needle='for(auto& r:x.resolution)r->initializeLocalAt(seed,begin);';assert s.count(needle)==1
s=s.replace(needle,'for(auto& r:x.resolution)r->initializePhaseReplayedAt(seed,begin);')
(a.output/'Phase57PhaseReplay.cpp').write_text(s)
s=study.read_text();s=s.replace('local|head','local-v2');s=s.replace('const bool local=std::string(argv[8])=="local";require(local||std::string(argv[8])=="head","mode");','const bool local=std::string(argv[8])=="local-v2";require(local,"offline local-v2 mode required");')
s=s.replace('<<",\"input\":"<<input', '<<",\"local_policy\":\"local-v2\""<<",\"input\":"<<input')
(a.output/'Phase61PhaseReplayStudy.cpp').write_text(s)
manifest={'schema':'offline-phase-replay-experiment-v1','product_implementation':False,'oracle_rebuilt':False,'algorithm':'prefix FFT/phase replay; finite OLA/FIR rebuilt by unchanged local preroll','complexity':'O(seed input frames); no Ready 200ms promise','source_root':str(a.source.resolve()),'input_sources':original,'generated_sources':{str(x.relative_to(a.output)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(a.output.rglob('*')) if x.is_file()}}
(a.output/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest))
