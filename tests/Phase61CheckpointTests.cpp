#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase56PinnedWav.h"
#include <bit>
#include <fstream>
#include <iostream>
using namespace ts;using namespace ts::prototype;
void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
int main(int argc,char** argv){try{
    require(argc==2,"input.wav");phase56::PinnedWavSource source(argv[1],73);
    phase56::ProgressiveAnalysisSession analysis(source.rate(),source.channels(),73,{},{500000});
    while(source.appendNext(analysis,5003)){}source.finish(analysis);const auto snapshot=analysis.getSnapshot();
    std::ifstream file(argv[1],std::ios::binary);std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{}),different=bytes;
    const int fd=open(argv[1],O_RDONLY|O_CLOEXEC);require(fd>=0,"fd");
    for(std::uint32_t target:{0u,400000u,1500000u}){const bool dynamic=target!=0;
        phase57::ProgressiveSynthesisEngine original(fd,500000,73,{},16*1024*1024,bytes);
        phase59::ProgressiveTransitionPlanner oldPlanner(source.rate(),source.frames(),73,500000,true),newPlanner(source.rate(),source.frames(),73,500000,true);
        if(dynamic){original.enableDynamicTransitions();oldPlanner.update(snapshot);newPlanner.update(snapshot);}
        else original.setDeclaredFinalOutputFrames(source.frames()*2);
        original.supplySnapshot(snapshot);if(dynamic)require(original.trySupplyBorrowedDynamicMap(oldPlanner.view().get()),"initial map");
        const phase57::ProgressiveSynthesisEngine::Sink discard=[](auto,auto,auto,auto){};
        for(unsigned i=0;i<8;++i)require(original.advance(discard)==phase57::SynthesisState::Produced,"prefix produce");
        require(!original.cloneFixedCheckpoint(fd,different),"different resident identity accepted");
        auto copy=original.cloneFixedCheckpoint(fd,bytes);require(bool(copy),"fixed checkpoint missing");copy->prepareCheckpointForEpoch();
        const auto before=copy->frontier();require(copy->advance(discard)==phase57::SynthesisState::NeedsMoreAnalysis,"checkpoint used before context");
        require(copy->frontier().nextInput==before.nextInput&&copy->frontier().published==before.published,"context wait mutated checkpoint");
        copy->supplySnapshot(snapshot);
        if(dynamic){
            auto wrong=*newPlanner.view();auto nodes=wrong.map.starts();++nodes[1];wrong.map=TimeMap(1024,std::move(nodes),wrong.map.events());
            require(!copy->trySupplyBorrowedDynamicMap(&wrong),"different checkpoint map accepted");
            require(copy->trySupplyBorrowedDynamicMap(newPlanner.view().get()),"same checkpoint map rejected");
            const auto a=original.dspFrontier(),b=copy->dspFrontier();require(a.nextInput==b.nextInput&&a.lastProcessedInput==b.lastProcessedInput&&a.recentFrameInput==b.recentFrameInput&&a.recentFrameOutput==b.recentFrameOutput&&a.actualWeight==b.actualWeight,"checkpoint frontier/OLA/density differs");
            const auto old=oldPlanner.plan({target},1,0,before.published,a),next=newPlanner.plan({target},1,0,before.published,b);
            require(old.change.plan.applied()&&next.change.plan.applied()&&oldPlanner.view()->map.starts()==newPlanner.view()->map.starts(),"post-checkpoint Phase59 plan differs");
            if(target==400000)require(old.change.changesDensity&&next.change.changesDensity,"checkpoint density transition untested");
            require(original.trySupplyBorrowedDynamicMap(oldPlanner.view().get())&&copy->trySupplyBorrowedDynamicMap(newPlanner.view().get()),"post-checkpoint plan rejected");oldPlanner.confirmPlan(true);newPlanner.confirmPlan(true);
        }
        auto drain=[&](auto& engine){std::vector<float> pcm;std::size_t at=before.published;
            auto capture=[&](auto generation,auto offset,auto block,std::size_t n){require(generation==73&&offset==at,"checkpoint PCM order");for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<source.channels();++c)pcm.push_back(block[c][i]);at+=n;};
            while(engine.advance(capture)==phase57::SynthesisState::Produced){}require(engine.frontier().state==phase57::SynthesisState::Finished,"checkpoint EOS");return pcm;};
        const auto expected=drain(original),actual=drain(*copy);require(expected.size()==actual.size(),"checkpoint length");
        for(std::size_t i=0;i<actual.size();++i)require(std::bit_cast<std::uint32_t>(actual[i])==std::bit_cast<std::uint32_t>(expected[i]),"checkpoint phase/OLA/FIR PCM bits");
        require(!original.cloneFixedCheckpoint(fd,bytes),"finished state checkpointed");
    }
    close(fd);std::cout<<"PASS fixed/dynamic checkpoint full suffix, all phase/OLA/FIR/history state, map/input identity, Phase59 plan after restore\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
