#include "prototype/Phase58RealtimePipeline.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <tuple>
#include <utility>

namespace p58=ts::prototype::phase58;
namespace {
void need(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
constexpr std::uint64_t fifoFrames=16384,pendingFrames=2048,callbackFrames=4096,minimumPeriod=512;
constexpr std::uint64_t horizon=fifoFrames+pendingFrames+callbackFrames;
constexpr std::uint64_t maximumCycleDistance=1+(horizon-1)/minimumPeriod;
static_assert(horizon==22528&&maximumCycleDistance==44);
static_assert(std::tuple_size_v<p58::LoopPcmDescriptorRing> ==64);
static_assert(maximumCycleDistance<std::tuple_size_v<p58::LoopPcmDescriptorRing>);

p58::LoopPcmDescriptor sample(std::uint64_t cycle,float marker=0){
    p58::LoopPcmDescriptor value;value.cycle=cycle;
    value.first={float(cycle%4096)+marker,marker+0.25f};
    value.last={-float(cycle%4096)-marker,marker-0.5f};return value;
}
void publish(p58::LoopPcmDescriptorRing& ring,const p58::LoopPcmDescriptor& value){
    ring[value.cycle%ring.size()].publish(value);
}
void expect(const p58::LoopPcmDescriptor& actual,const p58::LoopPcmDescriptor& wanted){
    need(actual.cycle==wanted.cycle&&actual.first==wanted.first&&actual.last==wanted.last,"descriptor cycle/sample identity differs");
}
void emptyUnpublished(){
    p58::LoopPcmDescriptorRing ring;
    for(std::uint64_t cycle=0;cycle<ring.size()*2;++cycle)need(!p58::readLoopPcmDescriptor(ring,cycle),"unpublished descriptor accepted");
}
void wrapIdentity(){
    p58::LoopPcmDescriptorRing ring;
    // 環状枠を3回再利用する正常試験。下の強制した古いcycle拒否とは区別する。
    for(std::uint64_t cycle=0;cycle<3*ring.size();++cycle){
        const auto wanted=sample(cycle);publish(ring,wanted);
        const auto actual=p58::readLoopPcmDescriptor(ring,cycle);need(actual.has_value(),"fresh wrapped descriptor rejected");expect(*actual,wanted);
        need(!p58::readLoopPcmDescriptor(ring,cycle+ring.size()),"future cycle accepted from same slot");
        if(cycle>=ring.size())need(!p58::readLoopPcmDescriptor(ring,cycle-ring.size()),"old cycle accepted after normal wrap");
    }
}
void staleCycleRejected(){
    p58::LoopPcmDescriptorRing ring;constexpr std::uint64_t oldest=7;
    publish(ring,sample(oldest));need(p58::readLoopPcmDescriptor(ring,oldest).has_value(),"oldest setup not published");
    // 下位層で意図的にproducer/FIFO不変条件を迂回する。同じ枠をc+64で
    // 上書きした後、製品と同じ読出しが要求cycle cを拒否することを確かめる。
    const auto overtaking=oldest+ring.size();const auto wanted=sample(overtaking,64.f);publish(ring,wanted);
    need(!p58::readLoopPcmDescriptor(ring,oldest),"forced overtaking returned a different cycle's descriptor");
    const auto actual=p58::readLoopPcmDescriptor(ring,overtaking);need(actual.has_value(),"replacement descriptor unavailable");expect(*actual,wanted);
}
void fullWidthCycleIdentity(){
    p58::LoopPcmDescriptorRing ring;
    // 枠番号や切り詰めた番号でなく64bit全体を比較することを検査する。
    // producerの累積カウンタ自体がuint64_tを超えた後の動作の証明ではない。
    constexpr auto high=std::numeric_limits<std::uint64_t>::max()-7;
    const auto wanted=sample(high,7.f);publish(ring,wanted);
    const auto actual=p58::readLoopPcmDescriptor(ring,high);need(actual.has_value(),"full-width cycle unavailable");expect(*actual,wanted);
    need(!p58::readLoopPcmDescriptor(ring,high-ring.size()),"full-width stale cycle accepted");
    need(!p58::readLoopPcmDescriptor(ring,high-(std::uint64_t(1)<<32)),"32bit-truncated stale cycle accepted");
}
void valueLifetime(){
    p58::LoopPcmDescriptorRing ring;const auto wanted=sample(3,11.f);publish(ring,wanted);
    const auto copied=p58::readLoopPcmDescriptor(ring,wanted.cycle);need(copied.has_value(),"value-lifetime setup");
    for(std::uint64_t turn=1;turn<=9;++turn)publish(ring,sample(wanted.cycle+turn*ring.size(),float(turn)));
    need(!p58::readLoopPcmDescriptor(ring,wanted.cycle),"overwritten value still published as old cycle");
    expect(*copied,wanted); // 値コピーはmailboxの枠の再利用後も変化しない。
}
void twoSources(){
    p58::LoopPcmDescriptorRing oldSource,newSource;
    constexpr std::uint64_t oldCycle=9,newCycle=1003;
    for(std::uint64_t distance=0;distance<=maximumCycleDistance;++distance){
        publish(oldSource,sample(oldCycle+distance,20.f));publish(newSource,sample(newCycle+distance,40.f));
    }
    const auto oldValue=p58::readLoopPcmDescriptor(oldSource,oldCycle),newValue=p58::readLoopPcmDescriptor(newSource,newCycle);
    need(oldValue.has_value()&&newValue.has_value(),"two source descriptor horizons interfered");
    expect(*oldValue,sample(oldCycle,20.f));expect(*newValue,sample(newCycle,40.f));
}
void capacityBound(){
    // 証明の整数不等式を有限集合で検査する。DSPの模型やPCM生成ではなく、
    // 実rendererの境界試験の代用にも使用しない。
    for(std::uint64_t residual=1;residual<=minimumPeriod;++residual){
        for(const auto advance:std::array<std::uint64_t,10>{0,1,63,64,127,128,511,512,4095,callbackFrames}){
            const auto latestStart=fifoFrames+pendingFrames+advance;
            for(std::uint64_t distance=1;distance<=65;++distance){
                const auto required=residual+(distance-1)*minimumPeriod;
                if(required<=latestStart)need(distance<=maximumCycleDistance,"descriptor safety distance exceeds 44");
            }
        }
    }
    need(1+(maximumCycleDistance-1)*minimumPeriod<=horizon,"conservative endpoint absent");
    need(1+maximumCycleDistance*minimumPeriod>horizon,"45 cycles fit the protected horizon");
    need(1+(std::tuple_size_v<p58::LoopPcmDescriptorRing>-1)*minimumPeriod>horizon,"64-cycle overwrite fits the protected horizon");
}
using Test=void(*)();
constexpr std::array<std::pair<std::string_view,Test>,7> cases{{
    {"D08.empty_unpublished",emptyUnpublished},{"D08.slot_wrap_identity",wrapIdentity},
    {"D08.forced_stale_cycle_rejected",staleCycleRejected},{"D08.descriptor_value_lifetime",valueLifetime},
    {"D08.two_source_independence",twoSources},{"D08.capacity_bound",capacityBound},
    {"D08.full_width_cycle_identity",fullWidthCycleIdentity}
}};
}
int main(){
    std::size_t executed=0;
    try{
        for(const auto& [id,test]:cases){test();++executed;std::cout<<"{\"id\":\""<<id<<"\",\"status\":\"PASS\"}\n";}
        std::cout<<"{\"suite\":\"phase62_descriptor_invariant\",\"expected\":"<<cases.size()<<",\"executed\":"<<executed
                 <<",\"maximum_safe_cycle_distance\":"<<maximumCycleDistance<<",\"descriptor_capacity\":"<<std::tuple_size_v<p58::LoopPcmDescriptorRing>
                 <<",\"status\":\"PASS\",\"run_complete\":true,\"real_pipeline_overtaking\":false,\"realtime\":false}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<"phase62_descriptor_invariant FAIL after "<<executed<<'/'<<cases.size()<<": "<<error.what()<<'\n';return 1;}
}
