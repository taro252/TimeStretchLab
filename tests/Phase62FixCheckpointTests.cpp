#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase56PinnedWav.h"
#include "dsp/FFTAccelerate.h"
#include <bit>
#include <cmath>
#include <fstream>
#include <iostream>
using namespace ts;using namespace ts::prototype;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int main(int argc,char** argv){try{
    check(argc==2,"input");phase56::PinnedWavSource source(argv[1],73);phase56::ProgressiveAnalysisSession analysis(source.rate(),source.channels(),73,{},{500000,1000000});
    while(source.appendNext(analysis,5003)){}source.finish(analysis);const auto snapshot=analysis.getSnapshot();
    std::ifstream f(argv[1],std::ios::binary);std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(f)),{}),different=bytes;
    const int fd=open(argv[1],O_RDONLY|O_CLOEXEC);check(fd>=0,"input fd");
    {
        phase57::ProgressiveSynthesisEngine engine(fd,500000,73,{},16*1024*1024,bytes);engine.setDeclaredFinalOutputFrames(source.frames()*2);engine.supplySnapshot(snapshot);
        const phase57::ProgressiveSynthesisEngine::Sink discard=[](auto,auto,auto,auto){};
        for(unsigned i=0;i<8;++i)check(engine.advance(discard)==phase57::SynthesisState::Produced,"prefix");
        auto saved=engine.cloneFixedCheckpoint(fd,bytes);check(bool(saved),"complete seed");auto start=engine.frontier().published;
        phase57::ProgressiveSynthesisEngine wrongBytes(fd,500000,73,{},16*1024*1024,different);wrongBytes.setDeclaredFinalOutputFrames(source.frames()*2);wrongBytes.supplySnapshot(snapshot);check(!wrongBytes.restoreFixedLoopCheckpoint(*saved),"foreign resident bytes accepted");
        phase57::ProgressiveSynthesisEngine wrongSpeed(fd,1000000,73,{},16*1024*1024,bytes);wrongSpeed.setDeclaredFinalOutputFrames(source.frames());wrongSpeed.supplySnapshot(snapshot);check(!wrongSpeed.restoreFixedLoopCheckpoint(*saved),"foreign speed accepted");
        phase57::ProgressiveSynthesisEngine wrongAnalysis(fd,500000,73,{},16*1024*1024,bytes);wrongAnalysis.setDeclaredFinalOutputFrames(source.frames()*2);wrongAnalysis.supplySnapshot(std::make_shared<const phase56::AnalysisSnapshot>(*snapshot));check(!wrongAnalysis.restoreFixedLoopCheckpoint(*saved),"foreign immutable analysis version accepted");
        check(engine.advance(discard)==phase57::SynthesisState::Produced,"B state advance");check(engine.captureFixedLoopCheckpoint(*saved),"preallocated B state capture");start=engine.frontier().published;
        auto drain=[&]{std::vector<float> pcm;std::size_t at=start;const phase57::ProgressiveSynthesisEngine::Sink sink=[&](auto generation,auto offset,const float*const* samples,std::size_t n){check(generation==73&&offset==at,"restored raw order");for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<source.channels();++c){check(std::isfinite(samples[c][i]),"nonfinite");pcm.push_back(samples[c][i]);}at+=n;};while(engine.advance(sink)==phase57::SynthesisState::Produced){}check(engine.frontier().state==phase57::SynthesisState::Finished,"EOS");return pcm;};
        const auto expected=drain();const auto plans=FFTAccelerate::threadPlanCreations();
        for(unsigned i=0;i<3;++i){check(engine.restoreFixedLoopCheckpoint(*saved),"same full state rejected after EOS");const auto actual=drain();check(actual.size()==expected.size(),"restored count");for(std::size_t j=0;j<actual.size();++j)check(std::bit_cast<std::uint32_t>(actual[j])==std::bit_cast<std::uint32_t>(expected[j]),"phase/stereo/OLA/FIR/partial state bits");check(FFTAccelerate::threadPlanCreations()==plans,"warm FFT plan creation");}
        engine.cancel(); // Finished cancellation remains a no-op by the legacy contract.
    }
    close(fd);std::cout<<"PASS in-place complete fixed state, identity/speed/analysis rejection, EOS restart x3, no warm FFT plans\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
