#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase56PinnedWav.h"
#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase61SeekEnvelope.h"
#include <bit>
#include <fstream>
#include <iostream>
using namespace ts;using namespace ts::prototype;
void require(bool v,const char* why){if(!v)throw std::runtime_error(why);}
template<class F>void rejects(F action){bool rejected=false;try{action();}catch(const std::exception&){rejected=true;}require(rejected,"Invalid local context accepted");}
int main(int argc,char** argv){try{
    for(auto rate:{44100u,48000u}){
        phase61::PublicationEnvelope envelope(rate,2);std::array<float,2048> ones;ones.fill(1);const float* input[]={ones.data(),ones.data()};
        require(envelope.apply(input,0,2048,false,0)==input,"Default envelope changed Exact path");
        auto p=envelope.apply(input,100,2048,true,100);require(p[0][0]==0&&p[0][rate/200-1]==1&&p[1][2047]==1,"Fade-in endpoints");
        envelope.retireRequested=true;p=envelope.apply(input,2148,2048,false,0);
        require(p[0][0]==1&&p[0][rate/200-1]==0&&p[1][2047]==0&&envelope.retireEnd==2148+rate/200,"Fade-out endpoints");
        envelope.retireRequested=false;p=envelope.apply(input,4196,2048,false,0);require(p[0][0]==0&&p[0][rate/200-1]==1,"Cancelled fade restoration");
        require(envelope.apply(input,6244,2048,false,0)==input,"Inactive envelope copies Exact PCM");
    }
    require(argc==2,"input.wav");const int fd=open(argv[1],O_RDONLY|O_CLOEXEC);require(fd>=0,"FD");
    std::ifstream f(argv[1],std::ios::binary);std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(f)),{});
    phase56::PinnedWavSource source(fd,73);
    phase56::ProgressiveAnalysisSession a(source.rate(),source.channels(),73);
    while(source.appendNext(a,32768)){}source.finish(a);auto snapshot=a.getSnapshot();
    for(std::uint32_t speed=400000;speed<=2000000;speed+=10000){
        phase57::ProgressiveSynthesisEngine engine(fd,speed,73,{},16*1024*1024,bytes);
        rejects([&]{engine.initializeFastLocal(0,source.rate()/2);});
        engine.enableDynamicTransitions();engine.supplySnapshot(snapshot);
        phase59::ProgressiveTransitionPlanner planner(source.rate(),source.frames(),73,speed,true);planner.update(snapshot);
        require(engine.trySupplyBorrowedDynamicMap(planner.view().get()),"fixed map");
        rejects([&]{engine.initializeFastLocal(source.frames()+1,source.rate()/2);});
        rejects([&]{engine.initializeFastLocal(0,0);});
        const auto target=source.frames()/2+17;const auto start=engine.initializeFastLocal(target,source.rate()/2);
        require(start.requestedInput==target&&start.requestedOutput==std::size_t(std::llround(planner.view()->map.outputPositionForInputSample(double(target)))),"Coordinate error");
        require(start.beginOutput%14336==0&&start.seedInput%(speed<500000?1024:2048)==0,"Absolute FIR/hop grid");
        require(start.beginOutput<=start.requestedOutput&&start.seedInput<=target,"Preroll after target");
        rejects([&]{engine.initializeFastLocal(target,source.rate()/2);});
        require(!engine.cloneFixedCheckpoint(fd,bytes),"Local checkpoint accepted as Exact");
    }
    std::size_t cases=0;
    for(auto speed:{400000u,500000u,750000u,1000000u,1250000u,1500000u,2000000u})for(bool candidate:{true,false}){
        phase59::ProgressiveTransitionPlanner planner(source.rate(),source.frames(),73,speed,candidate);planner.update(snapshot);
        for(auto target:{std::size_t(0),source.frames()/2+17,source.frames()-1,source.frames()}){
            auto render=[&](bool local){
                phase57::ProgressiveSynthesisEngine engine(fd,speed,73,{},16*1024*1024,bytes);engine.enableDynamicTransitions();engine.supplySnapshot(snapshot);
                require(engine.trySupplyBorrowedDynamicMap(planner.view().get()),"final map");
                const auto point=local?engine.initializeFastLocal(target,source.rate()/2):phase57::LocalSeekStart{};
                std::size_t at=point.beginOutput,written=0;std::vector<float> pcm;
                const auto wanted=target==source.frames()?planner.view()->outputFrames:std::min(planner.view()->outputFrames,std::size_t(std::llround(planner.view()->map.outputPositionForInputSample(double(target)))));
                const auto sink=[&](auto generation,auto offset,auto p,std::size_t n){
                    require(generation==73&&offset==at,"Gap/duplicate/generation");at+=n;
                    for(std::size_t i=0;i<n;++i)if(offset+i>=wanted){for(std::size_t c=0;c<source.channels();++c){require(std::isfinite(p[c][i]),"Nonfinite PCM");pcm.push_back(p[c][i]);}++written;}
                };
                while(engine.advance(sink)==phase57::SynthesisState::Produced){}
                require(engine.frontier().state==phase57::SynthesisState::Finished&&at==planner.view()->outputFrames&&written==at-wanted,"Suffix/EOS count");
                return pcm;
            };
            const auto first=render(true),second=render(true);require(first==second,"Local seek not deterministic");
            if(target==0)require(first==render(false),"Local start zero changed Exact PCM");
            ++cases;
        }
    }
    close(fd);std::cout<<"PASS 161 speed acceptance, invalid context, absolute FIR/hop grids, no Exact checkpoint contamination, "<<cases<<" deterministic full suffix/EOS cases; quality is a separate gate\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
