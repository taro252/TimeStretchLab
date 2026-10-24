#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase56PinnedWav.h"
#include <bit>
#include <fstream>
#include <iostream>
#include <cmath>
#include <tuple>
using namespace ts;using namespace ts::prototype;
void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
namespace {
bool sameCheckpointFrontier(const phase57::SynthesisFrontier& a,const phase57::SynthesisFrontier& b){
    return std::tie(a.generation,a.receivedInput,a.detectorThrough,a.closedEvents,a.mapThroughNode,
        a.nextInput,a.lastInput,a.readableInputThrough,a.olaThrough,a.firSourceThrough,a.firThrough,
        a.generated,a.published,a.outputFrames,a.state)==
        std::tie(b.generation,b.receivedInput,b.detectorThrough,b.closedEvents,b.mapThroughNode,
        b.nextInput,b.lastInput,b.readableInputThrough,b.olaThrough,b.firSourceThrough,b.firThrough,
        b.generated,b.published,b.outputFrames,b.state);
}
bool sameCheckpointDsp(const Phase36StreamingSpeedEngine::Frontier& a,const Phase36StreamingSpeedEngine::Frontier& b){
    if(std::tie(a.preparedOutput,a.nextInput,a.lastProcessedInput,a.finalizedOla,a.firstUnprocessedFirSource,
        a.recentFrameInput,a.recentFrameOutput,a.recentFrameCount,a.actualWeightSample)!=
       std::tie(b.preparedOutput,b.nextInput,b.lastProcessedInput,b.finalizedOla,b.firstUnprocessedFirSource,
        b.recentFrameInput,b.recentFrameOutput,b.recentFrameCount,b.actualWeightSample))return false;
    for(std::size_t i=0;i<a.actualWeight.size();++i)if(!std::isfinite(a.actualWeight[i])||!std::isfinite(b.actualWeight[i])||
        std::bit_cast<std::uint32_t>(a.actualWeight[i])!=std::bit_cast<std::uint32_t>(b.actualWeight[i]))return false;
    return true;
}
std::vector<float> checkpointReference(const char* path,std::size_t samples){
    std::ifstream f(path,std::ios::binary|std::ios::ate);require(bool(f)&&f.tellg()==std::streamoff(samples*sizeof(float)),"checkpoint frozen reference length");
    std::vector<float> pcm(samples);f.seekg(0);f.read(reinterpret_cast<char*>(pcm.data()),std::streamsize(samples*sizeof(float)));
    require(bool(f),"checkpoint frozen reference read");for(float v:pcm)require(std::isfinite(v),"checkpoint frozen reference NaN/Inf");return pcm;
}
void checkpointBits(const std::vector<float>& actual,const std::vector<float>& reference,std::size_t offset){
    require(offset<=reference.size()&&actual.size()==reference.size()-offset,"checkpoint independent suffix length");
    for(std::size_t i=0;i<actual.size();++i)require(std::isfinite(actual[i])&&
        std::bit_cast<std::uint32_t>(actual[i])==std::bit_cast<std::uint32_t>(reference[offset+i]),"checkpoint independent suffix PCM bits");
}
// This fixture declares a specific safe rejection, not an arbitrary failure.
// The original positive .4/1.5 assertions below remain unchanged for mix.wav.
void checkpointSafeRejection(const char* input,const char* oldReference,const char* newReference){
    phase56::PinnedWavSource source(input,73);
    require(source.frames()>=source.rate()*16ULL&&source.frames()<=source.rate()*20ULL,"checkpoint rejection fixture must be 16..20 seconds");
    phase56::ProgressiveAnalysisSession analysis(source.rate(),source.channels(),73,{},{500000,400000});
    while(source.appendNext(analysis,5003)){}source.finish(analysis);const auto snapshot=analysis.getSnapshot();
    const std::size_t oldFrames=source.frames()*2;
    const std::size_t newFrames=(source.frames()*1000000ULL+200000)/400000;
    const auto oldPcm=checkpointReference(oldReference,oldFrames*source.channels()),newPcm=checkpointReference(newReference,newFrames*source.channels());
    std::ifstream file(input,std::ios::binary);std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    struct Descriptor {int fd;~Descriptor(){if(fd>=0)close(fd);}} descriptor{open(input,O_RDONLY|O_CLOEXEC)};require(descriptor.fd>=0,"checkpoint rejection fd");
    std::size_t comparedSuffixFrames=0;
    for(bool duplicate:{false,true}){
        phase57::ProgressiveSynthesisEngine original(descriptor.fd,500000,73,{},16*1024*1024,bytes);
        phase59::ProgressiveTransitionPlanner left(source.rate(),source.frames(),73,500000,true,true),right(source.rate(),source.frames(),73,500000,true,true),wrong(source.rate(),source.frames(),73,400000,true);
        left.update(snapshot);right.update(snapshot);wrong.update(snapshot);original.enableDynamicTransitions();original.supplySnapshot(snapshot);
        require(original.trySupplyBorrowedDynamicMap(left.view().get()),"checkpoint rejection initial Map");
        const phase57::ProgressiveSynthesisEngine::Sink discard=[](auto,auto,auto,auto){};
        for(unsigned i=0;i<8;++i)require(original.advance(discard)==phase57::SynthesisState::Produced,"checkpoint rejection prefix");
        auto copy=original.cloneFixedCheckpoint(descriptor.fd,bytes);require(bool(copy),"checkpoint rejection complete state missing");copy->prepareCheckpointForEpoch();copy->supplySnapshot(snapshot);
        const auto unbound=copy->frontier();const auto unboundDsp=copy->dspFrontier();
        require(!copy->trySupplyBorrowedDynamicMap(wrong.view().get()),"checkpoint accepted incompatible speed Map");
        require(sameCheckpointFrontier(unbound,copy->frontier())&&sameCheckpointDsp(unboundDsp,copy->dspFrontier()),"incompatible Map mutated checkpoint");
        require(copy->trySupplyBorrowedDynamicMap(right.view().get()),"checkpoint rejected compatible Map");
        const auto before=original.frontier(),copyBefore=copy->frontier();const auto a=original.dspFrontier(),b=copy->dspFrontier();
        require(sameCheckpointDsp(a,b),"checkpoint rejection restored DSP frontier differs");
        const auto lm=left.view(),rm=right.view();
        const auto l=left.plan({400000},1,0,before.published,a),r=right.plan({400000},1,0,before.published,b);
        require(l.status==phase59::PlanningStatus::Decided&&r.status==phase59::PlanningStatus::Decided&&!l.limitReached&&!r.limitReached&&
            l.change.plan.outcome==Phase39Outcome::NoSafeInterval&&r.change.plan.outcome==Phase39Outcome::NoSafeInterval&&
            !l.change.plan.applied()&&!r.change.plan.applied(),"checkpoint fixture did not produce the declared NoSafeInterval");
        const auto unchanged=[&]{return left.view().get()==lm.get()&&right.view().get()==rm.get()&&
            left.historyCount()==0&&right.historyCount()==0&&left.tail().micros==500000&&right.tail().micros==500000&&
            sameCheckpointFrontier(before,original.frontier())&&sameCheckpointFrontier(copyBefore,copy->frontier())&&
            sameCheckpointDsp(a,original.dspFrontier())&&sameCheckpointDsp(b,copy->dspFrontier());};
        require(unchanged(),"safe rejection mutated Map/history/DSP/unpublished state");
        if(duplicate){
            const auto ld=left.plan({500000},2,0,before.published,a),rd=right.plan({500000},2,0,before.published,b);
            require(ld.status==phase59::PlanningStatus::Decided&&rd.status==phase59::PlanningStatus::Decided&&
                ld.change.plan.outcome==Phase39Outcome::Duplicate&&rd.change.plan.outcome==Phase39Outcome::Duplicate&&!ld.limitReached&&!rd.limitReached,
                "checkpoint rejection poisoned following same-speed request");require(unchanged(),"duplicate after rejection mutated state");
        }
        const auto drain=[&](auto& engine){std::vector<float> pcm;std::size_t at=before.published;
            const auto sink=[&](auto generation,auto offset,auto block,std::size_t n){require(generation==73&&offset==at,"checkpoint rejection PCM order");
                for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<source.channels();++c)pcm.push_back(block[c][i]);at+=n;};
            while(engine.advance(sink)==phase57::SynthesisState::Produced){}require(engine.frontier().state==phase57::SynthesisState::Finished,"checkpoint rejection EOS");return pcm;};
        const auto expected=drain(original),actual=drain(*copy);checkpointBits(expected,oldPcm,before.published*source.channels());checkpointBits(actual,oldPcm,before.published*source.channels());
        comparedSuffixFrames+=actual.size()/source.channels();
        std::cout<<"{\"case\":\""<<(duplicate?"rejected_then_duplicate":"rejected_pcm_unchanged")<<"\",\"PASS\":true,\"outcome\":\"NoSafeInterval\",\"published\":"<<before.published<<",\"suffix_frames\":"<<actual.size()/source.channels()<<",\"independent_fixed_PCM\":true}\n";
    }
    // Both old synthesis instances and the checkpoint above are gone before
    // explicit fixed Exact re-preparation. This is not a dynamic FIFO flush.
    phase57::ProgressiveSynthesisEngine fresh(descriptor.fd,400000,73,{},16*1024*1024,bytes);fresh.setDeclaredFinalOutputFrames(newFrames);fresh.supplySnapshot(snapshot);
    std::vector<float> rebuilt;std::size_t at=0;const auto sink=[&](auto generation,auto offset,auto block,std::size_t n){require(generation==73&&offset==at,"checkpoint Exact recovery order");for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<source.channels();++c)rebuilt.push_back(block[c][i]);at+=n;};
    while(fresh.advance(sink)==phase57::SynthesisState::Produced){}require(fresh.frontier().state==phase57::SynthesisState::Finished,"checkpoint Exact recovery EOS");checkpointBits(rebuilt,newPcm,0);
    std::cout<<"{\"case\":\"explicit_fixed_Exact_reprepare\",\"PASS\":true,\"frames\":"<<at<<",\"independent_fixed_PCM\":true,\"old_checkpoint_reused_at_wrong_speed\":false}\n";
    std::cout<<"{\"suite\":\"checkpoint_safe_rejection\",\"PASS\":true,\"expected\":3,\"completed\":3,\"compared_suffix_frames\":"<<comparedSuffixFrames<<",\"new_exact_frames\":"<<at<<",\"audio_output\":false,\"performance_approval\":false}\n";
}
}
int main(int argc,char** argv){try{
    if(argc==5&&std::string(argv[2])=="--expect-no-safe-interval"){checkpointSafeRejection(argv[1],argv[3],argv[4]);return 0;}
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
            auto wrong=*newPlanner.view();const auto flat=wrong.map.materialize();auto nodes=flat.starts();++nodes[1];wrong.map=TimeMap(1024,std::move(nodes),flat.events());
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
