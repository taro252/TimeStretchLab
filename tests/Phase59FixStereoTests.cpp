#include "prototype/Phase35StereoPhaseCoherence.h"
#include "reference/phase59_fix/Before59FixStereoPhaseCoherence.h"
#include <bit>
#include <algorithm>
#include <cstdint>
#include <iostream>
using namespace ts::prototype;
namespace {
std::uint32_t state=0x59c0ffee;
float randomValue(){state^=state<<13;state^=state>>17;state^=state<<5;return float(state&65535)/32768.f-1.f;}
void same(std::complex<float> a,std::complex<float> b){if(std::bit_cast<std::uint64_t>(a)!=std::bit_cast<std::uint64_t>(b))throw std::runtime_error("Stereo differs from frozen Phase59");}
}
int main(){try{
    std::size_t cases=0;
    for(std::size_t size:{16,1024,4096,8192})for(float strength:{0.f,.65f,1.f})for(int alias:{0,1,2,3,4}){
        const auto bins=size/2+1;
        Phase35PhaseVocoder left(size,int(size/4),true,48000),right(size,int(size/4),true,48000);
        Before59FixPhaseVocoder oldLeft(size,int(size/4),true,48000),oldRight(size,int(size/4),true,48000);
        Phase35StereoPhaseCoherence stereo(size,48000,strength,.4f);
        Before59FixStereoPhaseCoherence oldStereo(size,48000,strength,.4f);
        std::vector<int> owners(bins,-1);
        for(std::size_t k=1;k+1<bins;++k)owners[k]=int(std::clamp((k/7)*7+3,std::size_t(1),bins-2));
        for(unsigned frame=0;frame<32;++frame){
            std::vector<std::complex<float>> a(bins+2),b(bins+2),oldA,oldB,outA(bins+2),outB(bins+2),oldOutA(bins+2),oldOutB(bins+2);
            for(std::size_t k=0;k<a.size();++k){
                float scale=k%17==0?0.f:k%13==0?1e-8f:k%7==3?5.f:.1f;
                a[k]={randomValue()*scale,randomValue()*scale};
                b[k]=a[k]*std::complex<float>(k%11==0?1.5f:.73f,.13f);
            }
            oldA=a;oldB=b;
            const auto offset=alias==4?1u:0u;
            const auto* inL=a.data()+offset;const auto* inR=b.data()+offset;
            const auto* oldInL=oldA.data()+offset;const auto* oldInR=oldB.data()+offset;
            auto* resultL=alias==1?a.data():alias==2?b.data():alias==3?a.data()+1:alias==4?a.data():outA.data();
            auto* resultR=alias==1?b.data():alias==2?a.data():alias==3?b.data()+1:alias==4?b.data():outB.data();
            auto* oldResultL=alias==1?oldA.data():alias==2?oldB.data():alias==3?oldA.data()+1:alias==4?oldA.data():oldOutA.data();
            auto* oldResultR=alias==1?oldB.data():alias==2?oldA.data():alias==3?oldB.data()+1:alias==4?oldB.data():oldOutB.data();
            left.process(inL,resultL,size/8.+.125,frame%8==0,true,.7f,&owners);
            oldLeft.process(oldInL,oldResultL,size/8.+.125,frame%8==0,true,.7f,&owners);
            right.process(inR,resultR,size/8.+.125,frame%8==0,true,.7f,&owners);
            oldRight.process(oldInR,oldResultR,size/8.+.125,frame%8==0,true,.7f,&owners);
            stereo.process(inL,inR,resultL,resultR,left,right,owners);
            oldStereo.process(oldInL,oldInR,oldResultL,oldResultR,oldLeft,oldRight,owners);
            for(std::size_t k=0;k<bins;++k){same(resultL[k],oldResultL[k]);same(resultR[k],oldResultR[k]);}
            for(std::size_t k=0;k<bins;++k)if(std::bit_cast<std::uint32_t>(stereo.weights()[k])!=std::bit_cast<std::uint32_t>(oldStereo.weights()[k]))throw std::runtime_error("Stereo weight differs");
            if(std::bit_cast<std::uint64_t>(stereo.averageWeight())!=std::bit_cast<std::uint64_t>(oldStereo.averageWeight()))throw std::runtime_error("Stereo weight sum differs");
            if(frame==15){stereo.reset();oldStereo.reset();left.reset();right.reset();oldLeft.reset();oldRight.reset();}
            ++cases;
        }
    }
    std::cout<<"PASS frozen_stereo_frames="<<cases<<" (disjoint, in-place, crossed, overlap, reset)\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
