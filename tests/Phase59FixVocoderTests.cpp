#include "prototype/Phase35PhaseVocoder.h"
#include "reference/phase59_fix/Before59FixPhaseVocoder.h"
#include <bit>
#include <cstdint>
#include <iostream>
using namespace ts::prototype;
namespace {
void require(bool value){if(!value)throw std::runtime_error("Vocoder differs from frozen Phase59 implementation");}
std::uint32_t randomState=0x59f1c0de;
float value(){randomState^=randomState<<13;randomState^=randomState>>17;randomState^=randomState<<5;return (float(randomState&65535)/32768.f-1.f)*.3f;}
bool same(std::complex<float> a,std::complex<float> b){return std::bit_cast<std::uint64_t>(a)==std::bit_cast<std::uint64_t>(b);}
}
int main(){try{
    std::size_t cases=0;
    for(const std::size_t size:{16,512,1024,2048,4096,8192})for(bool locking:{false,true})for(bool shared:{false,true})for(int alias:{0,1,2,3}){
        Phase35PhaseVocoder current(size,128,locking,48000);
        Before59FixPhaseVocoder frozen(size,128,locking,48000);
        ts::PhaseLocker owners(size);
        const auto bins=size/2+1;
        std::vector<std::complex<float>> input(bins+2),a(bins+2),b(bins+2),aligned(bins);
        for(unsigned frame=0;frame<40;++frame){
            for(std::size_t k=0;k<input.size();++k){
                auto scale=k%7==0?0.f:k%11==0?1e-7f:k%13==0?1e-8f:1.f;
                input[k]={value()*scale,value()*scale};
                if(k<aligned.size())aligned[k]={value(),value()};
            }
            owners.analyzePeaks(input.data(),bins);
            auto suppliedOwners=owners.ownerPeak();
            if(frame%5==0)for(std::size_t k=1;k+1<bins;k+=11)suppliedOwners[k]=int(bins-1);
            const auto* peakOwners=shared?&suppliedOwners:nullptr;
            const auto inputOffset=alias==3?1u:0u;
            const auto outputOffset=alias==2?1u:0u;
            a=input;b=input;
            const auto* inputA=alias?a.data()+inputOffset:input.data();
            const auto* inputB=alias?b.data()+inputOffset:input.data();
            auto* outputA=a.data()+outputOffset;auto* outputB=b.data()+outputOffset;
            const bool reset=frame%7==0,selective=frame%3!=0;
            const double hop=frame%2?51.2:256.75;
            current.process(inputA,outputA,hop,reset,selective,.73f,peakOwners,frame%3?128:64);
            frozen.process(inputB,outputB,hop,reset,selective,.73f,peakOwners,frame%3?128:64);
            for(std::size_t k=0;k<bins;++k)require(same(outputA[k],outputB[k]));
            if(frame%9==0){
                current.resynchronize(input.data(),aligned.data(),outputA,peakOwners);
                frozen.resynchronize(input.data(),aligned.data(),outputB,peakOwners);
                for(std::size_t k=0;k<bins;++k)require(same(outputA[k],outputB[k]));
            }
            if(frame==19){current.reset();frozen.reset();}
            ++cases;
        }
    }
    std::cout<<"PASS frozen_vocoder_frames="<<cases<<" (disjoint, in-place, overlapping, reset, resynchronize)\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
