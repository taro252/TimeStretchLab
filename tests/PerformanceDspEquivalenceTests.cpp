#include "prototype/Phase35PhaseVocoder.h"
#include "prototype/Phase35StereoPhaseCoherence.h"
#include "reference/performance_response/Frozen5674PhaseVocoder.h"
#include "reference/performance_response/Frozen5674StereoPhaseCoherence.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <complex>
#include <cstdint>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

// This is a scalar spectrum/state comparison, not a whole-render, device,
// real-time, or performance approval. The independent reference implementation
// is extracted from commit 5674; see reference/performance_response/PROVENANCE.json.
namespace {
using Complex = std::complex<float>;
using PV = ts::prototype::Phase35PhaseVocoder;
using FrozenPV = ts::prototype::Frozen5674PhaseVocoder;
using Stereo = ts::prototype::Phase35StereoPhaseCoherence;
using FrozenStereo = ts::prototype::Frozen5674StereoPhaseCoherence;
using PolarView = PV::InputPolarView;
constexpr std::array<std::size_t,3> fftSizes{1024,4096,8192};
constexpr unsigned framesPerCase=32;
constexpr std::array<const char*,5> pvAliases{
    "disjoint","inplace","partial_forward","partial_backward","adjacent"};
constexpr std::array<const char*,9> stereoAliases{
    "disjoint","inplace","partial_forward","partial_backward","cross_swap",
    "cross_one","cross_partial","shared_output","adjacent"};
constexpr std::size_t expectedCases=3*(2*2*5+3*9+4+1);
constexpr std::uint64_t expectedFrames=141*35+12*8+3*7;
constexpr std::uint64_t expectedResynchronizations=60*4+81*8+3;
constexpr std::uint64_t expectedCopyForks=141,expectedRestores=144;
constexpr std::uint64_t expectedStereoViewSelections=81*(35+4);
static_assert(sizeof(Complex)==sizeof(std::uint64_t));

struct Counts {
    std::uint64_t complexValues=0,floatValues=0,doubleValues=0;
    std::uint64_t frames=0,resynchronizations=0,copyForks=0,restores=0;
    std::uint64_t validViews=0,invalidViews=0,viewSelections=0;
};
Counts totals;
std::string context;
void require(bool value,std::string_view detail) {
    if(!value)throw std::runtime_error(context+": "+std::string(detail));
}
void equalBits(float a,float b,std::string_view detail) {
    ++totals.floatValues;
    require(std::isfinite(a)&&std::isfinite(b),"nonfinite Float32");
    require(std::bit_cast<std::uint32_t>(a)==std::bit_cast<std::uint32_t>(b),detail);
}
void equalBits(double a,double b,std::string_view detail) {
    ++totals.doubleValues;
    require(std::isfinite(a)&&std::isfinite(b),"nonfinite Float64");
    require(std::bit_cast<std::uint64_t>(a)==std::bit_cast<std::uint64_t>(b),detail);
}
void equalBits(Complex a,Complex b,std::string_view detail) {
    ++totals.complexValues;
    require(std::isfinite(a.real())&&std::isfinite(a.imag())&&
            std::isfinite(b.real())&&std::isfinite(b.imag()),"nonfinite complex Float32");
    require(std::bit_cast<std::uint64_t>(a)==std::bit_cast<std::uint64_t>(b),detail);
}
void equalArena(const std::vector<Complex>& a,const std::vector<Complex>& b) {
    require(a.size()==b.size(),"arena length");
    for(std::size_t k=0;k<a.size();++k) {
        if(std::bit_cast<std::uint64_t>(a[k])!=std::bit_cast<std::uint64_t>(b[k]))
            throw std::runtime_error(context+": spectrum/guard bits at arena bin "+std::to_string(k));
        equalBits(a[k],b[k],"spectrum/guard bits");
    }
}
template<class A,class B> void equalLocker(const A& a,const B& b) {
    require(a.ownerPeak()==b.ownerPeak(),"peak owners");
    require(a.magnitudes().size()==b.magnitudes().size(),"magnitude length");
    for(std::size_t k=0;k<a.magnitudes().size();++k)
        equalBits(a.magnitudes()[k],b.magnitudes()[k],"peak magnitudes");
    require(a.peaks().size()==b.peaks().size(),"peak count");
    for(std::size_t k=0;k<a.peaks().size();++k) {
        require(a.peaks()[k].bin==b.peaks()[k].bin,"peak bin");
        equalBits(a.peaks()[k].position,b.peaks()[k].position,"peak position");
        equalBits(a.peaks()[k].magnitude,b.peaks()[k].magnitude,"peak magnitude");
    }
}
void equalStereo(const Stereo& a,const FrozenStereo& b) {
    require(a.weights().size()==b.weights().size(),"coherence weight length");
    for(std::size_t k=0;k<a.weights().size();++k)
        equalBits(a.weights()[k],b.weights()[k],"coherence weight bits");
    equalBits(a.averageWeight(),b.averageWeight(),"coherence cumulative average bits");
    require(a.lastNeighborhoodEvaluations()==b.lastNeighborhoodEvaluations(),
            "owner neighborhood evaluation count");
}

// Exact axis values straddle the Float32 floor; multiplying random values by
// 1e-7 would not test the floor itself. Each address is reused across frames.
Complex sample(std::size_t k,unsigned frame,unsigned channel) {
    const float floor=1e-7f;
    const std::array<float,8> edges{0.0f,std::numeric_limits<float>::denorm_min(),
        1e-10f,std::nextafter(floor,0.0f),floor,
        std::nextafter(floor,std::numeric_limits<float>::infinity()),2e-7f,0.2f};
    if(k<17 || k%19==0) {
        const float magnitude=edges[(k+frame+channel*3)%edges.size()];
        switch((k/2+frame/8+channel)%4) {
            case 0:return {magnitude,0.0f};
            case 1:return {-magnitude,-0.0f};
            case 2:return {0.0f,magnitude};
            default:return {-0.0f,-magnitude};
        }
    }
    const float channelScale=channel ? (frame/6%2?1.5f:0.73f) : 1.0f;
    const float magnitude=(k%7==3?6.0f:0.025f)*channelScale;
    const float phase=float(k%113)*0.061f+float(frame)*0.023f+float(channel)*0.37f;
    return {magnitude*std::cos(phase),magnitude*std::sin(phase)};
}
std::vector<int> owners(std::size_t bins,unsigned frame,const Complex* input) {
    ts::Frozen5674PhaseLocker detector((bins-1)*2);
    detector.analyzePeaks(input,bins);
    auto result=detector.ownerPeak();
    for(std::size_t k=1;k+1<bins;++k) {
        switch(frame%8) {
            case 0:break; // Frozen, independently generated peak map.
            case 1:result[k]=int(k);break;
            case 2:result[k]=int(std::clamp((k/7)*7+3,std::size_t(1),bins-2));break;
            case 3:result[k]=int(k%2?bins-2:1);break; // Both directions in one frame.
            case 4:result[k]=int(bins-1);break; // Public API permits Nyquist owners.
            case 5:result[k]=k%5==0?-1:k%5==1?0:k%5==2?int(k):
                                  k%5==3?int(bins-1):int(std::min(k+1,bins-2));break;
            case 6:if(k%11==0)result[k]=int(bins-1);break;
            default:result[k]=int((k*31+7)%(bins-1)+1);break;
        }
    }
    return result;
}
struct PvLayout {std::size_t input=0,output=0;};
PvLayout pvLayout(std::size_t bins,unsigned alias) {
    switch(alias) {
        case 0:return {0,2*bins+2};
        case 1:return {0,0};
        case 2:return {0,1};
        case 3:return {1,0};
        default:return {0,bins}; // Boundary of the disjointness test.
    }
}
struct StereoLayout {std::size_t inL=0,inR=0,outL=0,outR=0;};
StereoLayout stereoLayout(std::size_t bins,unsigned alias) {
    StereoLayout x{0,2*bins+4,4*bins+8,6*bins+12};
    switch(alias) {
        case 1:x.outL=x.inL;x.outR=x.inR;break;
        case 2:x.outL=x.inL+1;x.outR=x.inR+1;break;
        case 3:x.inL=1;x.inR+=1;x.outL=0;x.outR=x.inR-1;break;
        case 4:x.outL=x.inR;x.outR=x.inL;break;
        case 5:x.outL=x.inR;break;
        case 6:x.outL=x.inR+1;break;
        case 7:x.outR=x.outL;break;
        case 8:x.outL=x.inL+bins;x.outR=x.inR+bins;break;
        default:break;
    }
    return x;
}
bool disjoint(const Complex* a,const Complex* b,std::size_t bins) {
    const auto x=reinterpret_cast<std::uintptr_t>(a),y=reinterpret_cast<std::uintptr_t>(b);
    return (x<y?y-x:x-y)/sizeof(Complex)>=bins;
}
void checkView(const PV& pv,const PolarView& view,const Complex* input,
               std::size_t bins,bool expected) {
    require(view.validFor(pv,input,bins)==expected,"polar view validity");
    if(!expected) {++totals.invalidViews;return;}
    ++totals.validViews;
    require(!view.validFor(pv,input+1,bins),"shifted input accepted by polar view");
    require(!view.validFor(pv,input,bins-1),"wrong bin count accepted by polar view");
    require(!view.phaseValid(0),"DC phase is not published");
    for(std::size_t k=1;k<bins;++k) {
        const float magnitude=std::abs(input[k]);
        equalBits(view.magnitude[k],magnitude,"published magnitude bits");
        require(view.phaseValid(k)==(magnitude>=1e-7f),"published phase-valid floor");
        if(view.phaseValid(k))equalBits(view.phase[k],std::arg(input[k]),"published phase bits");
    }
}
void unpublished(const PV& pv,std::string_view detail) {
    const auto view=pv.inputPolarView();
    require(!view.validFor(pv,view.input,view.bins),detail);
}
struct FrameOptions {
    double hop;
    bool reset,selective;
    float event;
    int analysisOverride;
};
FrameOptions options(std::size_t size,unsigned frame) {
    return {frame%2?double(size)/8+0.125:double(size)*0.4+0.75,
        frame%7==0,frame%3!=0,frame%5==0?0.0f:frame%5==1?1.0f:0.73f,
        frame%3==0?0:int(frame%3==1?size/4:size/8)};
}
void pvFrame(PV& current,FrozenPV& frozen,std::size_t size,bool locking,bool shared,
             unsigned alias,unsigned frame) {
    const auto bins=size/2+1;
    const auto layout=pvLayout(bins,alias);
    std::vector<Complex> a(4*bins+8,Complex(-0.0f,0.03125f));
    for(std::size_t k=0;k<bins;++k)a[layout.input+k]=sample(k,frame,0);
    auto b=a;
    const auto owner=owners(bins,frame,a.data()+layout.input);
    const auto* supplied=shared?&owner:nullptr;
    const auto oldView=current.inputPolarView();
    const auto p=options(size,frame);
    current.process(a.data()+layout.input,a.data()+layout.output,p.hop,
                    p.reset,p.selective,p.event,supplied,p.analysisOverride);
    frozen.process(b.data()+layout.input,b.data()+layout.output,p.hop,
                   p.reset,p.selective,p.event,supplied,p.analysisOverride);
    require(!oldView.validFor(current,a.data()+layout.input,bins),"previous process view survived");
    equalArena(a,b);
    equalLocker(current.phaseLocker(),frozen.phaseLocker());
    const bool reusable=locking&&shared&&disjoint(a.data()+layout.input,a.data()+layout.output,bins);
    const auto view=current.inputPolarView();
    checkView(current,view,a.data()+layout.input,bins,reusable);
    const PV copied=current;
    require(!view.validFor(copied,a.data()+layout.input,bins),"another PV accepted view");
    unpublished(copied,"copy constructor retained borrowed polar storage");
    if(frame%8==3) {
        std::vector<Complex> scheduled(bins),aligned(bins);
        for(std::size_t k=0;k<bins;++k) {
            scheduled[k]=sample(k,frame+1,0);aligned[k]=sample(k,frame+9,1);
        }
        current.resynchronize(scheduled.data(),aligned.data(),a.data()+layout.output,supplied);
        frozen.resynchronize(scheduled.data(),aligned.data(),b.data()+layout.output,supplied);
        equalArena(a,b);
        require(!view.validFor(current,a.data()+layout.input,bins),"resynchronize retained old view");
        unpublished(current,"resynchronize republished scheduled/aligned cache");
        ++totals.resynchronizations;
    }
    ++totals.frames;
}
void pvCase(std::size_t size,bool locking,bool shared,unsigned alias) {
    const double rate=alias%2?44100.0:48000.0;
    PV current(size,int(size/4),locking,rate);
    FrozenPV frozen(size,int(size/4),locking,rate);
    std::optional<PV> saved;
    std::optional<FrozenPV> oldSaved;
    std::optional<PolarView> savedView;
    for(unsigned frame=0;frame<framesPerCase;++frame) {
        context="pv fft="+std::to_string(size)+" locking="+std::to_string(locking)+
                " shared="+std::to_string(shared)+" alias="+pvAliases[alias]+" frame="+std::to_string(frame);
        if(frame==16) {
            current=*saved;frozen=*oldSaved;++totals.restores;
            unpublished(current,"restore view unexpectedly valid");
            require(!savedView->validFor(current,savedView->input,size/2+1),
                    "restore revived original owner's expired frame token");
        }
        if(frame==24) {
            const auto view=current.inputPolarView();
            current.reset();frozen.reset();
            require(!view.validFor(current,view.input,size/2+1),"reset retained previous view");
            unpublished(current,"reset published a view");
        }
        pvFrame(current,frozen,size,locking,shared,alias,frame);
        if(frame==8) {saved.emplace(current);oldSaved.emplace(frozen);savedView=current.inputPolarView();}
        if(frame==12) {
            auto fork=current;auto oldFork=frozen;
            for(unsigned i=0;i<3;++i)pvFrame(fork,oldFork,size,locking,shared,0,frame+100+i);
            ++totals.copyForks;
        }
    }
    current.reset();frozen.reset();
    unpublished(current,"reset view unexpectedly valid");
    equalLocker(current.phaseLocker(),frozen.phaseLocker());
}

struct CurrentStereoState {
    PV left,right;
    Stereo stereo;
    CurrentStereoState(std::size_t size,double rate,float strength):
        left(size,int(size/4),true,rate),right(size,int(size/4),true,rate),
        stereo(size,rate,strength,0.4f) {}
    void reset() {left.reset();right.reset();stereo.reset();}
};
struct FrozenStereoState {
    FrozenPV left,right;
    FrozenStereo stereo;
    FrozenStereoState(std::size_t size,double rate,float strength):
        left(size,int(size/4),true,rate),right(size,int(size/4),true,rate),
        stereo(size,rate,strength,0.4f) {}
    void reset() {left.reset();right.reset();stereo.reset();}
};
void stereoFrame(CurrentStereoState& current,FrozenStereoState& frozen,
                 std::size_t size,unsigned alias,unsigned frame) {
    const auto bins=size/2+1;
    const auto x=stereoLayout(bins,alias);
    std::vector<Complex> a(8*bins+20,Complex(0.015625f,-0.0f));
    for(std::size_t k=0;k<bins;++k) {
        a[x.inL+k]=sample(k,frame,0);a[x.inR+k]=sample(k,frame,1);
    }
    auto b=a;
    const auto owner=owners(bins,frame,a.data()+x.inL);
    const auto oldLeft=current.left.inputPolarView(),oldRight=current.right.inputPolarView();
    const auto p=options(size,frame);
    current.left.process(a.data()+x.inL,a.data()+x.outL,p.hop,p.reset,p.selective,p.event,&owner,p.analysisOverride);
    frozen.left.process(b.data()+x.inL,b.data()+x.outL,p.hop,p.reset,p.selective,p.event,&owner,p.analysisOverride);
    equalArena(a,b);
    // Inspect the left view before the right PV can overwrite a cross-aliased input.
    const auto left=current.left.inputPolarView();
    checkView(current.left,left,a.data()+x.inL,bins,disjoint(a.data()+x.inL,a.data()+x.outL,bins));
    current.right.process(a.data()+x.inR,a.data()+x.outR,p.hop,p.reset,p.selective,p.event,&owner,p.analysisOverride);
    frozen.right.process(b.data()+x.inR,b.data()+x.outR,p.hop,p.reset,p.selective,p.event,&owner,p.analysisOverride);
    equalArena(a,b);
    const auto right=current.right.inputPolarView();
    checkView(current.right,right,a.data()+x.inR,bins,disjoint(a.data()+x.inR,a.data()+x.outR,bins));
    require(!oldLeft.validFor(current.left,a.data()+x.inL,bins)&&
            !oldRight.validFor(current.right,a.data()+x.inR,bins),"stale stereo frame accepted");
    require(!left.validFor(current.right,a.data()+x.inL,bins)&&
            !right.validFor(current.left,a.data()+x.inR,bins),"cross-owner polar view accepted");
    const PolarView *leftArg=nullptr,*rightArg=nullptr;
    // Fresh, absent, stale, exchanged, and one-sided views all retain the
    // baseline arithmetic. Cross aliasing must force the same safe fallback.
    switch(frame%6) {
        case 0:break;
        case 1:leftArg=&left;rightArg=&right;break;
        case 2:leftArg=&oldLeft;rightArg=&oldRight;break;
        case 3:leftArg=&right;rightArg=&left;break;
        case 4:leftArg=&left;break;
        default:rightArg=&right;break;
    }
    // Also exercise both fresh views with repeated adjacent owner regions.
    if(frame%8==2) {leftArg=&left;rightArg=&right;}
    current.stereo.process(a.data()+x.inL,a.data()+x.inR,a.data()+x.outL,a.data()+x.outR,
                           current.left,current.right,owner,leftArg,rightArg);
    frozen.stereo.process(b.data()+x.inL,b.data()+x.inR,b.data()+x.outL,b.data()+x.outR,
                          frozen.left,frozen.right,owner);
    ++totals.viewSelections;
    equalArena(a,b);
    equalLocker(current.left.phaseLocker(),frozen.left.phaseLocker());
    equalLocker(current.right.phaseLocker(),frozen.right.phaseLocker());
    equalStereo(current.stereo,frozen.stereo);
    if(frame%8==3) {
        std::vector<Complex> scheduledL(bins),scheduledR(bins),alignedL(bins),alignedR(bins);
        for(std::size_t k=0;k<bins;++k) {
            scheduledL[k]=sample(k,frame+1,0);scheduledR[k]=sample(k,frame+1,1);
            alignedL[k]=sample(k,frame+9,0);alignedR[k]=sample(k,frame+9,1);
        }
        current.left.resynchronize(scheduledL.data(),alignedL.data(),a.data()+x.outL,&owner);
        frozen.left.resynchronize(scheduledL.data(),alignedL.data(),b.data()+x.outL,&owner);
        current.right.resynchronize(scheduledR.data(),alignedR.data(),a.data()+x.outR,&owner);
        frozen.right.resynchronize(scheduledR.data(),alignedR.data(),b.data()+x.outR,&owner);
        require(!left.validFor(current.left,a.data()+x.inL,bins)&&
                !right.validFor(current.right,a.data()+x.inR,bins),"resynchronized stereo view accepted");
        // Passing expired views explicitly must recompute from scheduled input,
        // never the aligned phases used by resynchronize.
        current.stereo.process(scheduledL.data(),scheduledR.data(),a.data()+x.outL,a.data()+x.outR,
                               current.left,current.right,owner,&left,&right);
        frozen.stereo.process(scheduledL.data(),scheduledR.data(),b.data()+x.outL,b.data()+x.outR,
                              frozen.left,frozen.right,owner);
        ++totals.viewSelections;
        equalArena(a,b);equalStereo(current.stereo,frozen.stereo);
        totals.resynchronizations+=2;
    }
    ++totals.frames;
}
void stereoCase(std::size_t size,float strength,unsigned alias) {
    const double rate=alias%2?44100.0:48000.0;
    CurrentStereoState current(size,rate,strength);
    FrozenStereoState frozen(size,rate,strength);
    std::optional<CurrentStereoState> saved;
    std::optional<FrozenStereoState> oldSaved;
    std::optional<PolarView> savedLeft,savedRight;
    for(unsigned frame=0;frame<framesPerCase;++frame) {
        context="stereo fft="+std::to_string(size)+" strength="+std::to_string(strength)+
                " alias="+stereoAliases[alias]+" frame="+std::to_string(frame);
        if(frame==16) {
            current=*saved;frozen=*oldSaved;++totals.restores;
            unpublished(current.left,"left restore published a view");
            unpublished(current.right,"right restore published a view");
            require(!savedLeft->validFor(current.left,savedLeft->input,size/2+1)&&
                    !savedRight->validFor(current.right,savedRight->input,size/2+1),
                    "stereo restore revived original owner's expired token");
        }
        if(frame==24) {
            const auto left=current.left.inputPolarView(),right=current.right.inputPolarView();
            current.reset();frozen.reset();
            require(!left.validFor(current.left,left.input,size/2+1)&&
                    !right.validFor(current.right,right.input,size/2+1),"stereo reset retained previous view");
            unpublished(current.left,"left reset published a view");
            unpublished(current.right,"right reset published a view");
        }
        stereoFrame(current,frozen,size,alias,frame);
        if(frame==8) {
            saved.emplace(current);oldSaved.emplace(frozen);
            savedLeft=current.left.inputPolarView();savedRight=current.right.inputPolarView();
        }
        if(frame==12) {
            auto fork=current;auto oldFork=frozen;
            unpublished(fork.left,"copied left stereo owner retained borrowed view");
            unpublished(fork.right,"copied right stereo owner retained borrowed view");
            for(unsigned i=0;i<3;++i)stereoFrame(fork,oldFork,size,0,frame+100+i);
            ++totals.copyForks;
        }
    }
    current.reset();frozen.reset();
    equalStereo(current.stereo,frozen.stereo);
}
// A short owner map was already safe for process (its trailing bins keep basic
// propagation). Do not call resynchronize/coherence with such maps: those APIs
// require an owner for every bin. Oversized/out-of-range maps are not exercised.
void shortOwnersCase(std::size_t size,unsigned countKind) {
    const auto bins=size/2+1;
    const std::array<std::size_t,4> lengths{0,1,2,bins/2};
    const auto length=lengths[countKind];
    PV current(size,int(size/4),true,48000);
    FrozenPV frozen(size,int(size/4),true,48000);
    std::vector<Complex> input(bins),a(bins),b(bins);
    std::vector<int> owner(length,-1);
    for(unsigned frame=0;frame<8;++frame) {
        context="short owners fft="+std::to_string(size)+" count="+std::to_string(length)+
                " frame="+std::to_string(frame);
        for(std::size_t k=0;k<bins;++k)input[k]=sample(k,frame,0);
        for(std::size_t k=1;k+1<length;++k)owner[k]=frame%2?int(bins-1):int(k);
        std::fill(a.begin(),a.end(),Complex(0.375f,-0.125f));b=a;
        current.process(input.data(),a.data(),double(size)/8+0.375,frame==0,true,0.73f,&owner);
        frozen.process(input.data(),b.data(),double(size)/8+0.375,frame==0,true,0.73f,&owner);
        equalArena(a,b);equalLocker(current.phaseLocker(),frozen.phaseLocker());
        ++totals.frames;
    }
}
void viewLifetimeCase(std::size_t size) {
    const auto bins=size/2+1;
    PV current(size,int(size/4),true,48000);
    FrozenPV frozen(size,int(size/4),true,48000);
    std::vector<Complex> input(bins),a(bins),b(bins),aligned(bins);
    std::vector<int> owner(bins,-1);
    for(std::size_t k=1;k+1<bins;++k)owner[k]=int(std::clamp((k/7)*7+3,std::size_t(1),bins-2));
    PolarView previous;
    for(unsigned frame=0;frame<6;++frame) {
        context="view lifetime fft="+std::to_string(size)+" frame="+std::to_string(frame);
        for(std::size_t k=0;k<bins;++k)
            input[k]=frame==0||frame==3?Complex(0.0f,frame==3?-0.0f:0.0f):sample(k,frame,0);
        // input.data() and output.data() remain identical across all six calls.
        current.process(input.data(),a.data(),double(size)/8+0.125,false,true,0.73f,&owner);
        frozen.process(input.data(),b.data(),double(size)/8+0.125,false,true,0.73f,&owner);
        equalArena(a,b);
        require(!previous.validFor(current,input.data(),bins),"same-address next frame retained old token");
        previous=current.inputPolarView();checkView(current,previous,input.data(),bins,true);
        auto wrong=previous;wrong.frame+=1;
        require(!wrong.validFor(current,input.data(),bins),"wrong frame token accepted");
        wrong=previous;wrong.magnitude=nullptr;
        require(!wrong.validFor(current,input.data(),bins),"foreign magnitude storage accepted");
        wrong=previous;wrong.phase=nullptr;
        require(!wrong.validFor(current,input.data(),bins),"foreign phase storage accepted");
        require(!previous.phaseValid(bins),"out-of-range phase published");
        ++totals.frames;
    }
    const auto token=current.inputPolarView();
    auto saved=current;
    auto oldSaved=frozen;
    unpublished(saved,"copy published original storage");
    current.reset();frozen.reset();
    require(!token.validFor(current,input.data(),bins),"reset retained live token");
    unpublished(current,"reset published cache");
    current=saved;frozen=oldSaved;++totals.restores;
    unpublished(current,"same-owner assignment restored borrowed storage");
    require(!token.validFor(current,input.data(),bins),"same-owner assignment revived original token");
    for(std::size_t k=0;k<bins;++k) {input[k]=sample(k,17,0);aligned[k]=sample(k,31,1);}
    current.process(input.data(),a.data(),double(size)/4+0.25,false,true,1.0f,&owner);
    frozen.process(input.data(),b.data(),double(size)/4+0.25,false,true,1.0f,&owner);
    equalArena(a,b);++totals.frames;
    const auto beforeResync=current.inputPolarView();
    current.resynchronize(input.data(),aligned.data(),a.data(),&owner);
    frozen.resynchronize(input.data(),aligned.data(),b.data(),&owner);
    equalArena(a,b);++totals.resynchronizations;
    unpublished(current,"resync published cache");
    require(!beforeResync.validFor(current,input.data(),bins),"resync retained live frame token");
}
std::string quoted(std::string_view s) {
    std::string result="\"";
    for(char c:s) {if(c=='\\'||c=='\"')result+='\\';if(c=='\n')result+="\\n";else result+=c;}
    return result+'\"';
}
struct Case {std::string id;std::size_t fft;bool stereo,locking,shared;unsigned alias,strength;unsigned special=0;};
std::vector<Case> cases() {
    std::vector<Case> result;
    for(auto size:fftSizes) {
        for(bool locking:{false,true})for(bool shared:{false,true})for(unsigned alias=0;alias<pvAliases.size();++alias)
            result.push_back({"PV/"+std::to_string(size)+"/locking"+std::to_string(locking)+
                "/shared"+std::to_string(shared)+"/"+pvAliases[alias],size,false,locking,shared,alias,0});
        for(unsigned strength=0;strength<3;++strength)for(unsigned alias=0;alias<stereoAliases.size();++alias)
            result.push_back({"STEREO/"+std::to_string(size)+"/strength"+std::to_string(strength)+
                "/"+stereoAliases[alias],size,true,true,true,alias,strength});
        constexpr std::array<const char*,4> shortNames{"empty","one","two","half"};
        for(unsigned kind=0;kind<shortNames.size();++kind)
            result.push_back({"PVOWNER/"+std::to_string(size)+"/"+shortNames[kind],size,false,true,true,kind,0,1});
        result.push_back({"VIEW/"+std::to_string(size)+"/lifetime",size,false,true,true,0,0,2});
    }
    return result;
}
}
int main(int argc,char**) {
    if(argc!=1) {std::cerr<<"usage: performance_dsp_equivalence_tests\n";return 2;}
    const auto required=cases();
    if(required.size()!=expectedCases)return 2;
    std::cout<<"EXPECTED {\"schema\":\"performance_response.dsp_equivalence.v1\","
        "\"reference_commit\":\"5674bd982d98caacaa3e87cdeae5bfc0b01c66ef\","
        "\"expected_cases\":"<<expectedCases<<",\"main_cases\":141,\"short_owner_cases\":12,\"lifetime_cases\":3,"
        "\"main_frames_per_case\":"<<framesPerCase<<",\"expected_frames\":"<<expectedFrames
        <<",\"expected_resynchronizations\":"<<expectedResynchronizations
        <<",\"expected_copy_forks\":"<<expectedCopyForks<<",\"expected_restores\":"<<expectedRestores
        <<",\"expected_stereo_view_selections\":"<<expectedStereoViewSelections<<",\"required_ids\":[";
    for(std::size_t i=0;i<required.size();++i)std::cout<<(i?",":"")<<quoted(required[i].id);
    std::cout<<"]}\n";
    std::size_t passed=0,failed=0;
    for(const auto& c:required) {
        try {
            if(c.special==1)shortOwnersCase(c.fft,c.alias);
            else if(c.special==2)viewLifetimeCase(c.fft);
            else if(c.stereo)stereoCase(c.fft,std::array<float,3>{0.0f,0.65f,1.0f}[c.strength],c.alias);
            else pvCase(c.fft,c.locking,c.shared,c.alias);
            ++passed;std::cout<<"CHECK {\"id\":"<<quoted(c.id)<<",\"pass\":true}\n";
        } catch(const std::exception& e) {
            ++failed;std::cout<<"CHECK {\"id\":"<<quoted(c.id)<<",\"pass\":false,\"detail\":"<<quoted(e.what())<<"}\n";
        }
    }
    const bool complete=passed+failed==required.size();
    const bool coverage=totals.frames==expectedFrames&&totals.resynchronizations==expectedResynchronizations&&
        totals.copyForks==expectedCopyForks&&totals.restores==expectedRestores&&
        totals.viewSelections==expectedStereoViewSelections&&totals.validViews>0&&totals.invalidViews>0;
    const bool pass=complete&&coverage&&failed==0;
    std::cout<<"SUMMARY {\"schema\":\"performance_response.dsp_equivalence.v1\",\"status\":"
        <<quoted(pass?"PASS":"FAIL")<<",\"run_complete\":"<<(complete?"true":"false")
        <<",\"coverage_pass\":"<<(coverage?"true":"false")
        <<",\"expected\":"<<expectedCases<<",\"passed\":"<<passed<<",\"failed\":"<<failed
        <<",\"frames_compared\":"<<totals.frames<<",\"resynchronizations\":"<<totals.resynchronizations
        <<",\"copy_forks\":"<<totals.copyForks<<",\"restores\":"<<totals.restores
        <<",\"complex_values_compared\":"<<totals.complexValues<<",\"float_values_compared\":"<<totals.floatValues
        <<",\"double_values_compared\":"<<totals.doubleValues<<",\"valid_views\":"<<totals.validViews
        <<",\"invalid_views\":"<<totals.invalidViews<<",\"stereo_view_selections\":"<<totals.viewSelections
        <<",\"whole_render_quality\":null,\"performance_pass\":null,\"rt_pass\":null}\n";
    return pass?0:1;
}
