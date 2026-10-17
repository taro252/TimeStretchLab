"""Build an ISOLATED local clock-phase hypothesis. Never changes product sources.

The hypothesis advances a locally estimated frequency over map(seed)-seed.
It cannot reconstruct arbitrary preceding frequency/reset history. Both users of
the private synthesis core are rebuilt together to avoid mixed class layouts.
"""
import argparse,hashlib,json,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    build=a.build.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    include=out/'include/prototype';include.mkdir(parents=True)
    core=(ROOT/'src/prototype/Phase36SynthesisCore.h').read_text()
    core=core.replace('#include <cmath>','#include <cmath>\n#include <numbers>')
    def replace(old,new):
        nonlocal core
        assert core.count(old)==1,old[:80]
        core=core.replace(old,new)
    replace('            nextEvent_=lo;\n        }\n    }\n    void copyRuntimeStateFrom',
            '            nextEvent_=lo;\n            position_=input-step;\n            for(std::size_t c=0;c<reader_.channels();++c)analyze(c,0);\n            localPrevious_=inputSpectra_;position_=input;localClockSeed_=true;\n        }\n    }\n    void copyRuntimeStateFrom')
    replace('    void processFrame() {',r'''    void applyLocalClock(std::size_t channel,const std::vector<int>* shared){
        if(!localClockSeed_)return;
        const auto& owners=shared?*shared:vocoders_[channel].phaseLocker().ownerPeak();
        const auto hop=hop_/(config_.timeRatio>2?2:1);
        const double delta=std::llround(detection_.position(double(position_)))-double(position_);
        if(!delta)return;
        for(std::size_t k=1;k<fftSize_/2;++k){
            const int owner=owners[k];if(owner<1||std::size_t(owner)>=fftSize_/2)continue;
            const auto reference=reader_.channels()==2&&std::abs(inputSpectra_[1][owner])>std::abs(inputSpectra_[0][owner])?1u:0u;
            const auto now=inputSpectra_[reference][owner],before=localPrevious_[reference][owner];
            if(std::abs(now)<1e-7f||std::abs(before)<1e-7f||std::abs(inputSpectra_[channel][k])<1e-7f)continue;
            const double omega=2*std::numbers::pi*owner/fftSize_;
            const double residual=std::remainder(double(std::arg(now))-std::arg(before)-omega*hop,2*std::numbers::pi);
            const double phase=std::remainder(double(std::arg(outputSpectra_[channel][k]))+(omega+residual/hop)*delta,2*std::numbers::pi);
            outputSpectra_[channel][k]=std::polar(std::abs(inputSpectra_[channel][k]),float(phase));
            vocoders_[channel].setOutputPhase(k,phase);
        }
    }
    void processFrame() {''')
    replace('delta,reset,config_.enableSelectivePhaseReset,strength,owners,actualAnalysisHop);',
            'delta,reset,config_.enableSelectivePhaseReset,strength,owners,actualAnalysisHop);\n                if(!reset)applyLocalClock(c,owners);')
    replace('                    actualAnalysisHop);\n                if (decision.applied)',
            '                    actualAnalysisHop);\n                if(!reset)applyLocalClock(c,nullptr);\n                if (decision.applied)')
    replace('        phaseMeasure.finish();','        localClockSeed_=false;phaseMeasure.finish();')
    replace('    WavStreamReader reader_;','    bool localClockSeed_=false;\n    std::vector<std::vector<std::complex<float>>> localPrevious_;\n    WavStreamReader reader_;')
    header=include/'Phase36SynthesisCore.h';header.write_text(core)
    link=shlex.split((build/'CMakeFiles/phase61_fast_seek_study.dir/link.txt').read_text())
    flags=next(l.split('=',1)[1].strip() for l in (build/'CMakeFiles/phase61_fast_seek_study.dir/flags.make').read_text().splitlines() if l.startswith('CXX_FLAGS ='))
    commands=[];objects=[]
    for stem in ('Phase36StreamingSpeedEngine','Phase57ProgressiveSynthesis'):
        source=out/(stem+'.cpp');source.write_bytes((ROOT/'src/prototype'/(stem+'.cpp')).read_bytes());obj=out/(stem+'.o');objects.append(str(obj))
        commands.append([link[0],*shlex.split(flags),'-arch','arm64','-I'+str(out/'include'),'-I'+str(ROOT/'src'),'-c',str(source),'-o',str(obj)])
    link[1:1]=objects;binary=out/'phase61_clock_study';link[link.index('-o')+1]=str(binary);commands.append(link)
    rows=[]
    for i,cmd in enumerate(commands):
        with (out/f'build_{i}.log').open('x') as f:result=subprocess.run(cmd,cwd=build,stdout=f,stderr=subprocess.STDOUT)
        rows.append({'command':cmd,'exit':result.returncode})
        if result.returncode:raise RuntimeError(str(out/f'build_{i}.log'))
    (out/'manifest.json').write_text(json.dumps({'hypothesis':'local instantaneous frequency times absolute map/input displacement; no claim of exact phase history','core_sha256':sha(header),'binary_sha256':sha(binary),'commands':rows},indent=2)+'\n')
    print(binary)
if __name__=='__main__':main()
