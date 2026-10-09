#include "dsp/TimeStretchProcessor.h"
#include "dsp/FFTAccelerate.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/PhaseLocker.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/RingOverlapAdd.h"
#include "dsp/STFT.h"
#include "dsp/StereoPhaseCoherence.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <complex>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace ts {
namespace {
constexpr std::size_t inputCapacity=65536;
constexpr std::size_t outputCapacity=65536;
constexpr std::size_t resolutionCache=32768;
constexpr std::size_t olaCapacity=32768;
constexpr std::size_t firCapacity=8192;
constexpr std::size_t mapCapacity=4096;
constexpr std::size_t midHop=1024;
class FiniteTransientDetector;

class PlanarFifo {
public:
    PlanarFifo(std::size_t channels,std::size_t capacity)
        : channels_(channels),capacity_(capacity),storage_(channels*capacity) {}
    void reset() noexcept {
        read_.store(0,std::memory_order_relaxed);
        write_.store(0,std::memory_order_relaxed);
    }
    std::size_t available() const noexcept {
        const auto r=read_.load(std::memory_order_acquire);
        const auto w=write_.load(std::memory_order_acquire);
        return w-r;
    }
    std::size_t free() const noexcept { return capacity_-available(); }
    std::size_t readPosition() const noexcept {
        return read_.load(std::memory_order_acquire);
    }
    std::size_t writePosition() const noexcept {
        return write_.load(std::memory_order_acquire);
    }
    void releaseThrough(std::size_t position) noexcept {
        read_.store(position,std::memory_order_release);
    }
    std::size_t push(const float* const* input,std::size_t frames) noexcept {
        const auto w=write_.load(std::memory_order_relaxed);
        const auto r=read_.load(std::memory_order_acquire);
        const auto count=std::min(frames,capacity_-(w-r));
        for (std::size_t c=0;c<channels_;++c)
            for (std::size_t i=0;i<count;++i)
                storage_[c*capacity_+(w+i)%capacity_]=input[c][i];
        write_.store(w+count,std::memory_order_release);
        return count;
    }
    void pushFrame(const std::array<float,2>& frame) noexcept {
        const auto w=write_.load(std::memory_order_relaxed);
        for (std::size_t c=0;c<channels_;++c)
            storage_[c*capacity_+w%capacity_]=frame[c];
        write_.store(w+1,std::memory_order_release);
    }
    std::size_t pull(float* const* output,std::size_t frames) noexcept {
        const auto r=read_.load(std::memory_order_relaxed);
        const auto w=write_.load(std::memory_order_acquire);
        const auto count=std::min(frames,w-r);
        for (std::size_t c=0;c<channels_;++c) {
            for (std::size_t i=0;i<count;++i)
                output[c][i]=storage_[c*capacity_+(r+i)%capacity_];
            std::fill(output[c]+count,output[c]+frames,0.0f);
        }
        read_.store(r+count,std::memory_order_release);
        return count;
    }
    float at(std::size_t channel,std::size_t index) const noexcept {
        return storage_[channel*capacity_+index%capacity_];
    }
    std::size_t bytes() const noexcept {return storage_.size()*sizeof(float);}
private:
    std::size_t channels_,capacity_;
    std::vector<float> storage_;
    alignas(64) std::atomic<std::size_t> read_{0};
    alignas(64) std::atomic<std::size_t> write_{0};
};

class LiveTimeline {
public:
    explicit LiveTimeline(double rate):rate_(rate) {reset(1.0);}
    void reset(double speed) noexcept {
        positions_.fill(0);
        globalPositions_.fill(0);
        mappedPositions_.fill(0);
        generated_=0;
        current_=rampTarget_=speed;
        rampStep_=0;
        rampRemaining_=0;
        debt_=maximumDebt_=0;
        lastRatio_=1.0/speed;
    }
    double current() const noexcept {return current_;}
    double debt() const noexcept {return debt_;}
    double maximumDebt() const noexcept {return maximumDebt_;}
    double atInput(std::size_t sample,double target,
                   const FiniteTransientDetector* detector=nullptr) noexcept;
    double globalAtInput(std::size_t sample,double target,
                         const FiniteTransientDetector* detector=nullptr) noexcept;
private:
    double predictedGap(std::size_t peak,double target,
                        const FiniteTransientDetector& detector) const noexcept;
    double rate_,current_=1,rampTarget_=1,rampStep_=0;
    std::array<double,mapCapacity> positions_{};
    std::array<double,mapCapacity> globalPositions_{};
    std::array<double,mapCapacity> mappedPositions_{};
    std::size_t generated_=0,rampRemaining_=0;
    double debt_=0,maximumDebt_=0,lastRatio_=1;
};

class LiveFIR {
public:
    explicit LiveFIR(const MultiResolutionCrossover::Filter& filter)
        : fft_(4096),response_(filter.response),block_(4096),
          spectrum_(2049),transformed_(4096),accum_(firCapacity),
          taps_(filter.taps),center_(filter.taps/2) {}
    void reset() noexcept {
        std::fill(accum_.begin(),accum_.end(),0.0f);
        nextBlock_=base_=0;
    }
    template<class Source>
    bool ready(std::size_t index,bool ended,std::size_t finalLength,Source&& source) {
        if (index!=base_) return false;
        while (nextBlock_<=index+center_ && (!ended || nextBlock_<finalLength)) {
            const auto count=ended?std::min<std::size_t>(2048,finalLength-nextBlock_):2048;
            std::fill(block_.begin(),block_.end(),0.0f);
            for (std::size_t i=0;i<count;++i)
                if (!source(nextBlock_+i,block_[i])) return false;
            fft_.forward(block_.data(),spectrum_.data());
            for (std::size_t k=0;k<spectrum_.size();++k)
                spectrum_[k]*=response_[k];
            fft_.inverse(spectrum_.data(),transformed_.data());
            for (std::size_t i=0;i<count+taps_-1;++i) {
                const auto at=static_cast<long long>(nextBlock_+i)-
                              static_cast<long long>(center_);
                if (at<static_cast<long long>(base_)) continue;
                if (ended && at>=static_cast<long long>(finalLength)) continue;
                if (at>=static_cast<long long>(base_+accum_.size())) return false;
                accum_[static_cast<std::size_t>(at)%accum_.size()]+=transformed_[i];
            }
            nextBlock_+=2048;
        }
        return true;
    }
    float pop(std::size_t index) noexcept {
        const auto slot=index%accum_.size();
        const float value=accum_[slot];
        accum_[slot]=0;
        ++base_;
        return value;
    }
    std::size_t bytes() const noexcept {
        return response_.size()*sizeof(std::complex<float>)+
            spectrum_.size()*sizeof(std::complex<float>)+
            (block_.size()+transformed_.size()+accum_.size())*sizeof(float);
    }
private:
    FFTAccelerate fft_;
    std::vector<std::complex<float>> response_;
    std::vector<float> block_;
    std::vector<std::complex<float>> spectrum_;
    std::vector<float> transformed_,accum_;
    std::size_t taps_,center_,nextBlock_=0,base_=0;
};

class FiniteTransientDetector {
public:
    explicit FiniteTransientDetector(std::size_t channelCount,unsigned lookaheadMs)
        :channels_(channelCount),lookaheadMs_(lookaheadMs),stft_(4096),
         frame_(4096),spectrum_(2049),magnitudes_(2049),previousLog_(2049) {}
    void reset() noexcept {
        std::fill(previousLog_.begin(),previousLog_.end(),0.0f);
        frames_.fill({});events_.fill({});
        nextFrame_=0;eventCount_=anchorCount_=0;
        pending_=false;lastCandidate_=0;
    }
    std::size_t lookaheadFrames(double rate) const noexcept {
        return std::max<std::size_t>(1,static_cast<std::size_t>(
            std::ceil(rate*lookaheadMs_/1000.0/midHop)));
    }
    std::size_t preFrames(double rate) const noexcept {
        const auto budget=lookaheadFrames(rate);
        return budget>3?std::min<std::size_t>(2,budget-3):0;
    }
    std::size_t anchorPreFrames(double rate) const noexcept {
        return preFrames(rate);
    }
    template<class Source>
    bool ensure(std::size_t frame,double rate,std::size_t written,bool ended,
                Source&& source) {
        const auto target=frame+lookaheadFrames(rate);
        while (nextFrame_<=target) {
            if (!ended && nextFrame_*midHop+2048>written)return false;
            analyze(nextFrame_,written,source);
            ++nextFrame_;
        }
        return true;
    }
    double weight(std::size_t frame,double rate) const noexcept {
        double best=0;
        const auto pre=preFrames(rate);
        for (std::uint64_t i=eventCount_>32?eventCount_-32:0;i<eventCount_;++i) {
            const auto& event=events_[i%events_.size()];
            if (frame+pre<event.peakFrame || frame>event.peakFrame+5)continue;
            const double distance=frame<event.peakFrame
                ? double(event.peakFrame-frame)/(pre+1)
                : double(frame-event.peakFrame)/6.0;
            if (distance<1)
                best=std::max(best,0.5*(1+std::cos(std::numbers::pi*distance)));
        }
        return best;
    }
    bool resetAt(std::size_t frame,bool low) const noexcept {
        for (std::uint64_t i=eventCount_>32?eventCount_-32:0;i<eventCount_;++i) {
            const auto peak=events_[i%events_.size()].peakFrame;
            if (low ? (peak+1)/2==frame : peak==frame)return true;
        }
        return false;
    }
    const RealtimeTransientEvent* eventNear(std::size_t frame,double rate) const noexcept {
        const auto pre=anchorPreFrames(rate);
        if (!pre)return nullptr;
        for (std::uint64_t i=eventCount_>32?eventCount_-32:0;i<eventCount_;++i) {
            const auto& event=events_[i%events_.size()];
            if (frame+pre>=event.peakFrame && frame<=event.peakFrame+7)
                return &event;
        }
        return nullptr;
    }
    std::uint64_t eventCount() const noexcept {return eventCount_;}
    std::uint64_t anchorCount() const noexcept {return anchorCount_;}
    bool event(std::uint64_t sequence,RealtimeTransientEvent& result) const noexcept {
        if (sequence>=eventCount_ || eventCount_-sequence>events_.size())return false;
        result=events_[sequence%events_.size()];return true;
    }
    std::size_t bytes() const noexcept {
        return (frame_.size()+magnitudes_.size()+previousLog_.size())*sizeof(float)+
            spectrum_.size()*sizeof(std::complex<float>)+sizeof(frames_)+sizeof(events_);
    }
private:
    struct FrameInfo {double flux=0,energy=0,threshold=0;float strength=0;bool candidate=false;};
    template<class Source>
    void analyze(std::size_t index,std::size_t written,Source& source) {
        std::fill(magnitudes_.begin(),magnitudes_.end(),0.0f);
        for (std::size_t c=0;c<channels_;++c) {
            for (std::size_t n=0;n<frame_.size();++n) {
                const auto at=static_cast<long long>(index*midHop+n)-2048;
                frame_[n]=at>=0 && static_cast<std::size_t>(at)<written
                    ? source(c,static_cast<std::size_t>(at)):0.0f;
            }
            stft_.analyze(frame_.data(),spectrum_.data());
            for (std::size_t k=0;k<magnitudes_.size();++k)
                magnitudes_[k]+=std::norm(spectrum_[k]);
        }
        double change=0,energy=0;
        for (std::size_t k=1;k+1<magnitudes_.size();++k) {
            const auto value=static_cast<float>(std::log1p(10.0*std::sqrt(magnitudes_[k])));
            change+=std::max(0.0,double(value-previousLog_[k]));
            energy+=value;previousLog_[k]=value;
        }
        auto& item=frames_[index%frames_.size()];
        item={change/(energy+1e-8),energy,0,0,false};
        std::array<double,12> history{},deviations{};
        const auto count=std::min<std::size_t>(12,index);
        for (std::size_t j=0;j<count;++j)
            history[j]=frames_[(index-count+j)%frames_.size()].flux;
        const auto median=[&](std::array<double,12>& data) {
            std::sort(data.begin(),data.begin()+count);
            if (!count)return 0.0;
            return count&1?data[count/2]:0.5*(data[count/2-1]+data[count/2]);
        };
        const auto baseline=median(history);
        for (std::size_t j=0;j<count;++j)
            deviations[j]=std::abs(frames_[(index-count+j)%frames_.size()].flux-baseline);
        const auto mad=median(deviations);
        item.threshold=std::max(0.01,baseline+3.0*mad);
        item.strength=static_cast<float>(std::clamp(
            (item.flux-item.threshold)/item.threshold,0.0,1.0));
        if (index>0) {
            const auto candidateIndex=index-1;
            auto& previous=frames_[candidateIndex%frames_.size()];
            const auto earlier=candidateIndex?frames_[(candidateIndex-1)%frames_.size()].flux:0;
            previous.candidate=candidateIndex>0 && previous.flux>=earlier &&
                previous.flux>item.flux && previous.flux>previous.threshold &&
                previous.strength>=0.25f && previous.energy>
                    frames_[(candidateIndex-1)%frames_.size()].energy*1.02 &&
                candidateIndex*midHop+2048<=written;
            if (previous.candidate) {
                if (!pending_ || candidateIndex-lastCandidate_>2 ||
                    candidateIndex-pendingStart_>5) {
                    if (pending_)publish(written,source);
                    pending_=true;pendingStart_=pendingPeak_=candidateIndex;
                    pendingStrength_=previous.strength;
                    pendingFlux_=previous.flux;
                } else if (previous.flux>pendingFlux_) {
                    pendingPeak_=candidateIndex;pendingFlux_=previous.flux;
                    pendingStrength_=previous.strength;
                }
                lastCandidate_=candidateIndex;
            }
            if (pending_ && index>=lastCandidate_+3)publish(written,source);
        }
    }
    template<class Source> void publish(std::size_t written,Source& source) {
        RealtimeTransientEvent event;
        event.sequence=eventCount_;event.peakFrame=pendingPeak_;
        event.inputSample=pendingPeak_*midHop;event.strength=pendingStrength_;
        const auto center=event.inputSample;
        const auto lo=center>midHop?center-midHop:0;
        const auto hi=std::min(written,center+2*midHop);
        if (hi>lo) {
            double sum=0,peak=0;std::size_t peakAt=lo;
            for (auto n=lo;n<hi;++n) {
                double power=0;
                for (std::size_t c=0;c<channels_;++c) {
                    const double value=source(c,n);power+=value*value;
                }
                sum+=power;
                if (power>peak) {peak=power;peakAt=n;}
            }
            if (sum>0 && std::sqrt(peak/(sum/(hi-lo)))>=20 &&
                peakAt>lo && peakAt+1<hi) {
                double runner=0;
                for (auto n=lo;n<hi;++n) {
                    if (n+4>=peakAt && n<=peakAt+4)continue;
                    double power=0;
                    for (std::size_t c=0;c<channels_;++c) {
                        const double value=source(c,n);power+=value*value;
                    }
                    runner=std::max(runner,power);
                }
                if (peak>=9*runner) {
                    event.inputSample=peakAt;event.preciseAnchor=true;++anchorCount_;
                }
            }
        }
        events_[eventCount_%events_.size()]=event;++eventCount_;
        pending_=false;
    }
    std::size_t channels_;unsigned lookaheadMs_;
    STFT stft_;
    std::vector<float> frame_;
    std::vector<std::complex<float>> spectrum_;
    std::vector<float> magnitudes_,previousLog_;
    std::array<FrameInfo,256> frames_{};
    std::array<RealtimeTransientEvent,256> events_{};
    std::size_t nextFrame_=0,pendingStart_=0,pendingPeak_=0,lastCandidate_=0;
    std::uint64_t eventCount_=0,anchorCount_=0;
    double pendingFlux_=0;
    float pendingStrength_=0;
    bool pending_=false;
};

double LiveTimeline::atInput(std::size_t sample,double target,
                             const FiniteTransientDetector* detector) noexcept {
    const auto frame=sample/midHop;
    while (generated_<=frame) {
        const auto next=generated_+1;
        if (target!=rampTarget_) {
            rampTarget_=target;
            rampRemaining_=std::max<std::size_t>(1,
                static_cast<std::size_t>(std::ceil(rate_*0.05/midHop)));
            rampStep_=(target-current_)/rampRemaining_;
        }
        if (rampRemaining_>0) {
            current_+=rampStep_;
            if (--rampRemaining_==0)current_=rampTarget_;
        }
        const double ratio=1.0/current_;
        double effective=ratio;
        if (detector) {
            const double budget=rate_*0.2;
            const auto depth=std::clamp((2*budget-debt_)/budget,0.0,1.0);
            const auto weight=ratio>1?detector->weight(generated_,rate_)*depth:0.0;
            effective=ratio+(1-ratio)*weight;
            if (weight<0.001 && debt_>0)
                effective+=std::min({debt_/(midHop*12.0),ratio*0.5,
                                     std::max(0.0,lastRatio_+0.4-effective)});
            effective=std::clamp(effective,std::max(0.25,ratio*0.5),ratio*1.5);
            effective=std::clamp(effective,lastRatio_-0.4,lastRatio_+0.4);
            debt_+=(ratio-effective)*midHop;
            // Roundoff must not leave an unbounded negative repayment balance.
            if (debt_<0)debt_=0;
            maximumDebt_=std::max(maximumDebt_,std::abs(debt_));
        }
        lastRatio_=effective;
        positions_[next%mapCapacity]=positions_[generated_%mapCapacity]+midHop*effective;
        globalPositions_[next%mapCapacity]=globalPositions_[generated_%mapCapacity]+midHop*ratio;
        generated_=next;
        double mapped=positions_[next%mapCapacity];
        if (detector) {
            const auto* event=detector->eventNear(next,rate_);
            if (event) {
                const auto peak=event->peakFrame;
                const auto pre=detector->anchorPreFrames(rate_);
                const double weight=next<=peak
                    ? 1.0-double(peak-next)/(pre+1)
                    : next<=peak+2 ? 1.0 : 1.0-double(next-peak-2)/6.0;
                const double offset=event->preciseAnchor
                    ? double(event->inputSample)-double(peak*midHop):0.0;
                const double correction=predictedGap(peak,target,*detector)+
                    (ratio-1)*offset;
                mapped+=std::max(0.0,weight)*correction;
            }
            const double previous=mappedPositions_[(next-1)%mapCapacity];
            mapped=std::clamp(mapped,previous+128.0,
                previous+midHop*std::min(3.0,ratio*1.5));
        }
        mappedPositions_[next%mapCapacity]=mapped;
    }
    const double u=double(sample%midHop)/midHop;
    return mappedPositions_[frame%mapCapacity]*(1-u)+
           mappedPositions_[(frame+1)%mapCapacity]*u;
}
double LiveTimeline::predictedGap(std::size_t peak,double target,
                                  const FiniteTransientDetector& detector) const noexcept {
    if (peak<=generated_)
        return globalPositions_[peak%mapCapacity]-positions_[peak%mapCapacity];
    double speed=current_,rampTarget=rampTarget_,rampStep=rampStep_;
    double debt=debt_,lastRatio=lastRatio_;
    auto remaining=rampRemaining_;
    for (auto frame=generated_;frame<peak;++frame) {
        if (target!=rampTarget) {
            rampTarget=target;
            remaining=std::max<std::size_t>(1,
                static_cast<std::size_t>(std::ceil(rate_*0.05/midHop)));
            rampStep=(target-speed)/remaining;
        }
        if (remaining>0) {
            speed+=rampStep;
            if (--remaining==0)speed=rampTarget;
        }
        const double ratio=1.0/speed;
        double effective=ratio;
        {
            const double budget=rate_*0.2;
            const auto depth=std::clamp((2*budget-debt)/budget,0.0,1.0);
            const auto weight=ratio>1?detector.weight(frame,rate_)*depth:0.0;
            effective=ratio+(1-ratio)*weight;
            if (weight<0.001 && debt>0)
                effective+=std::min({debt/(midHop*12.0),ratio*0.5,
                                     std::max(0.0,lastRatio+0.4-effective)});
            effective=std::clamp(effective,std::max(0.25,ratio*0.5),ratio*1.5);
            effective=std::clamp(effective,lastRatio-0.4,lastRatio+0.4);
            debt=std::max(0.0,debt+(ratio-effective)*midHop);
        }
        lastRatio=effective;
    }
    return debt;
}
double LiveTimeline::globalAtInput(std::size_t sample,double target,
                                   const FiniteTransientDetector* detector) noexcept {
    atInput(sample,target,detector);
    const auto frame=sample/midHop;
    const double u=double(sample%midHop)/midHop;
    return globalPositions_[frame%mapCapacity]*(1-u)+
           globalPositions_[(frame+1)%mapCapacity]*u;
}
}

struct TimeStretchProcessor::Impl {
    struct Resolution {
        Impl& parent;
        std::size_t size,hop,padding,channels;
        STFT stft;
        PhaseLocker sharedPeaks;
        StereoPhaseCoherence coherence;
        std::vector<PhaseVocoder> vocoders;
        std::vector<RingOverlapAdd> olas;
        std::vector<float> frame,synthesized;
        std::vector<std::vector<std::complex<float>>> inputSpectra,outputSpectra;
        std::vector<std::complex<float>> combined;
        std::vector<std::array<float,2>> cache;
        std::size_t nextFrame=0,produced=0;
        long long previousStart=0;
        Resolution(Impl& owner,std::size_t fftSize,std::size_t analysisHop)
            :parent(owner),size(fftSize),hop(analysisHop),padding(fftSize/2),
             channels(owner.channels),stft(fftSize),sharedPeaks(fftSize),
             coherence(fftSize,owner.rate,1.0f,0.5f),
             frame(fftSize),synthesized(fftSize),
             inputSpectra(channels,std::vector<std::complex<float>>(fftSize/2+1)),
             outputSpectra(channels,std::vector<std::complex<float>>(fftSize/2+1)),
             combined(fftSize/2+1),cache(resolutionCache) {
            vocoders.reserve(channels);olas.reserve(channels);
            for (std::size_t c=0;c<channels;++c) {
                vocoders.emplace_back(size,static_cast<int>(hop),true,parent.rate);
                olas.emplace_back(olaCapacity);
            }
        }
        void reset() noexcept {
            for (auto& vocoder:vocoders)vocoder.reset();
            for (auto& ola:olas)ola.reset();
            sharedPeaks.reset();coherence.reset();
            nextFrame=produced=0;previousStart=0;
        }
        bool startAt(std::size_t frame,long long& result) {
            return parent.mapStart(frame*hop,result);
        }
        bool frameReady() const noexcept {
            const auto write=parent.input.writePosition();
            if (parent.ended.load(std::memory_order_acquire)) {
                const auto count=(write+padding+hop-1)/hop+1;
                return nextFrame<count;
            }
            return nextFrame*hop+padding<=write;
        }
        void processFrame(long long start) {
            const auto center=nextFrame*hop;
            const auto write=parent.input.writePosition();
            for (std::size_t c=0;c<channels;++c) {
                for (std::size_t n=0;n<size;++n) {
                    const auto at=static_cast<long long>(center+n)-
                                  static_cast<long long>(padding);
                    frame[n]=at>=0 && static_cast<std::size_t>(at)<write
                        ? parent.input.at(c,static_cast<std::size_t>(at)):0.0f;
                }
                stft.analyze(frame.data(),inputSpectra[c].data());
            }
            const double delta=nextFrame==0?0.0:double(start-previousStart);
            const bool reset=parent.transient && parent.transient->resetAt(nextFrame,
                                                                          size==8192);
            if (channels==2) {
                for (std::size_t k=0;k<combined.size();++k)
                    combined[k]={std::hypot(std::abs(inputSpectra[0][k]),
                                            std::abs(inputSpectra[1][k])),0};
                sharedPeaks.analyzePeaks(combined.data(),combined.size());
                const auto& owners=sharedPeaks.ownerPeak();
                for (std::size_t c=0;c<channels;++c)
                    vocoders[c].process(inputSpectra[c].data(),outputSpectra[c].data(),
                        delta,reset,false,1.0f,&owners);
                coherence.process(inputSpectra[0].data(),inputSpectra[1].data(),
                    outputSpectra[0].data(),outputSpectra[1].data(),
                    vocoders[0],vocoders[1],owners);
            } else vocoders[0].process(inputSpectra[0].data(),outputSpectra[0].data(),
                                      delta,reset);
            for (std::size_t c=0;c<channels;++c) {
                stft.synthesize(outputSpectra[c].data(),synthesized.data());
                if (start<0 || start<static_cast<long long>(olas[c].nextAbsoluteSample()))
                    parent.faultCode.store(3,std::memory_order_relaxed);
                else if (static_cast<std::size_t>(start)+size>
                         olas[c].nextAbsoluteSample()+olas[c].capacity())
                    parent.faultCode.store(4,std::memory_order_relaxed);
                olas[c].add(synthesized.data(),stft.window().data(),size,start);
            }
            previousStart=start;
            ++nextFrame;
        }
        bool get(std::size_t channel,std::size_t index,float& value) {
            if (parent.haveFinal && index>=parent.finalLength) {value=0;return true;}
            while (produced<=index) {
                const auto absolute=produced+padding;
                long long start=0;
                while (true) {
                    if (!startAt(nextFrame,start))return false;
                    if (start>static_cast<long long>(absolute))break;
                    if (parent.ended.load(std::memory_order_acquire)) {
                        const auto length=parent.input.writePosition();
                        const auto frameCount=(length+padding+hop-1)/hop+1;
                        if (nextFrame>=frameCount)break;
                    }
                    if (!frameReady()) return false;
                    processFrame(start);
                }
                for (std::size_t c=0;c<channels;++c) {
                    while (olas[c].nextAbsoluteSample()<absolute)olas[c].pop();
                    cache[produced%cache.size()][c]=olas[c].pop();
                }
                ++produced;
            }
            if (index+cache.size()<produced) return false;
            value=cache[index%cache.size()][channel];
            return true;
        }
        std::size_t nextNeededInput() const noexcept {
            const auto center=nextFrame*hop;
            return center>padding?center-padding:0;
        }
        std::size_t bytes() const noexcept {
            return cache.size()*sizeof(std::array<float,2>)+
                (frame.size()+synthesized.size())*sizeof(float)+
                2*channels*combined.size()*sizeof(std::complex<float>)+
                channels*olaCapacity*2*sizeof(float);
        }
    };

    double rate;
    std::size_t channels,maxBlock;
    PlanarFifo input,output;
    LiveTimeline timeline;
    std::unique_ptr<FiniteTransientDetector> transient;
    MultiResolutionCrossover filters;
    Resolution low,mid;
    std::vector<std::unique_ptr<LiveFIR>> fir;
    std::atomic<double> targetSpeed{1.0},publishedSpeed{1.0};
    std::atomic<bool> ended{false},fault{false},workerStarted{false};
    std::atomic<int> faultCode{0};
    std::atomic<bool> workerFinished{false};
    std::atomic<std::uint64_t> inputUnderruns{0},outputUnderruns{0};
    std::atomic<std::uint64_t> inputOverruns{0},inputHighWater{0},outputHighWater{0};
    std::atomic<std::uint64_t> processingNanoseconds{0},workerCalls{0},resetCount{0};
    std::atomic<std::uint64_t> publishedEvents{0},publishedAnchors{0};
    std::atomic<double> publishedDebt{0},publishedMaximumDebt{0};
    std::size_t produced=0,finalLength=0;
    bool haveFinal=false;
    Impl(double sampleRate,std::size_t count,std::size_t block,
         RealtimeTransientConfig transientConfig)
        :rate(sampleRate),channels(count),maxBlock(block),
         input(count,inputCapacity),output(count,outputCapacity),timeline(sampleRate),
         filters(sampleRate,250.0),low(*this,8192,2048),mid(*this,4096,1024) {
        if (transientConfig.enabled)
            transient=std::make_unique<FiniteTransientDetector>(channels,
                transientConfig.lookaheadMilliseconds);
        fir.reserve(channels);
        for (std::size_t c=0;c<channels;++c)
            fir.emplace_back(std::make_unique<LiveFIR>(filters.lowFilter()));
    }
    void reset() noexcept {
        input.reset();output.reset();
        timeline.reset(targetSpeed.load(std::memory_order_relaxed));
        publishedSpeed.store(timeline.current(),std::memory_order_release);
        low.reset();mid.reset();
        if (transient)transient->reset();
        for (auto& item:fir)item->reset();
        ended.store(false,std::memory_order_release);
        fault.store(false,std::memory_order_release);
        faultCode.store(0,std::memory_order_release);
        workerStarted.store(false,std::memory_order_release);
        workerFinished.store(false,std::memory_order_release);
        produced=finalLength=0;haveFinal=false;
        inputUnderruns.store(0);outputUnderruns.store(0);inputOverruns.store(0);
        inputHighWater.store(0);outputHighWater.store(0);
        processingNanoseconds.store(0);workerCalls.store(0);
        publishedEvents.store(0);publishedAnchors.store(0);
        publishedDebt.store(0);publishedMaximumDebt.store(0);
        resetCount.fetch_add(1,std::memory_order_relaxed);
    }
    bool mapStart(std::size_t inputSample,long long& result) {
        if (transient) {
            const auto source=[&](std::size_t c,std::size_t n) {return input.at(c,n);};
            if (!transient->ensure(inputSample/midHop,rate,input.writePosition(),
                                   ended.load(std::memory_order_acquire),source))return false;
        }
        result=std::llround(timeline.atInput(inputSample,
            targetSpeed.load(std::memory_order_relaxed),transient.get()));
        return true;
    }
    void releaseInput() noexcept {
        const auto consumed=std::min(low.nextNeededInput(),mid.nextNeededInput());
        input.releaseThrough(std::min(consumed,input.writePosition()));
    }
    bool one() {
        if (ended.load(std::memory_order_acquire) && !haveFinal) {
            if (transient) {
                long long ignored=0;
                mapStart(input.writePosition(),ignored);
            }
            finalLength=static_cast<std::size_t>(std::llround(
                transient?timeline.globalAtInput(input.writePosition(),
                    targetSpeed.load(std::memory_order_relaxed),transient.get())
                    :timeline.atInput(input.writePosition(),
                    targetSpeed.load(std::memory_order_relaxed))));
            haveFinal=true;
        }
        if (haveFinal && produced>=finalLength) {
            workerFinished.store(true,std::memory_order_release);
            return false;
        }
        if (output.free()==0)return false;
        for (std::size_t c=0;c<channels;++c) {
            const auto source=[&](std::size_t index,float& value) {
                float l=0,m=0;
                if (!low.get(c,index,l) || !mid.get(c,index,m))return false;
                value=l-m;return true;
            };
            if (!fir[c]->ready(produced,haveFinal,finalLength,source))return false;
        }
        std::array<float,2> values{};
        for (std::size_t c=0;c<channels;++c) {
            float midSample=0;
            if (!mid.get(c,produced,midSample))return false;
            values[c]=midSample+fir[c]->pop(produced);
            if (!std::isfinite(values[c])) {
                faultCode.store(2,std::memory_order_release);
                fault.store(true,std::memory_order_release);
                return false;
            }
        }
        output.pushFrame(values);
        ++produced;
        releaseInput();
        const auto level=output.available();
        auto maximum=outputHighWater.load(std::memory_order_relaxed);
        while (level>maximum && !outputHighWater.compare_exchange_weak(
            maximum,level,std::memory_order_relaxed)) {}
        publishedSpeed.store(timeline.current(),std::memory_order_release);
        if (transient) {
            publishedEvents.store(transient->eventCount(),std::memory_order_release);
            publishedAnchors.store(transient->anchorCount(),std::memory_order_release);
            publishedDebt.store(timeline.debt(),std::memory_order_release);
            publishedMaximumDebt.store(timeline.maximumDebt(),std::memory_order_release);
        }
        return true;
    }
    ProcessorLatency latency() const noexcept {
        ProcessorLatency result;
        // First 2048-point FIR block needs output samples 0..2047.
        const double speed=targetSpeed.load(std::memory_order_relaxed);
        const auto furthestLowFrame=static_cast<std::size_t>(
            std::floor((2047.0+4096.0)*speed/2048.0));
        result.startupInputFrames=furthestLowFrame*2048+4096;
        if (transient) {
            const auto lookahead=transient->lookaheadFrames(rate)*midHop;
            result.transientLookahead=lookahead;
            result.startupInputFrames+=lookahead;
        }
        return result;
    }
    std::size_t bytes() const noexcept {
        std::size_t result=input.bytes()+output.bytes()+low.bytes()+mid.bytes();
        for (const auto& item:fir)result+=item->bytes();
        return result+filters.workingMemoryBytes()+(transient?transient->bytes():0);
    }
};

TimeStretchProcessor::TimeStretchProcessor()=default;
TimeStretchProcessor::~TimeStretchProcessor()=default;
void TimeStretchProcessor::prepare(double sampleRate,int channels,std::size_t maxBlockSize,
                                   RealtimeTransientConfig transient) {
    if (!std::isfinite(sampleRate) || sampleRate<8000 || sampleRate>192000 ||
        (channels!=1 && channels!=2) || maxBlockSize<1 || maxBlockSize>16384 ||
        (transient.enabled && transient.lookaheadMilliseconds!=64 &&
         transient.lookaheadMilliseconds!=128 &&
         transient.lookaheadMilliseconds!=192) ||
        (transient.enabled &&
         std::ceil(sampleRate*transient.lookaheadMilliseconds/1000.0/midHop)<3))
        throw std::invalid_argument("Invalid real-time processor format");
    impl_=std::make_unique<Impl>(sampleRate,static_cast<std::size_t>(channels),
                                 maxBlockSize,transient);
}
void TimeStretchProcessor::reset() noexcept {if (impl_)impl_->reset();}
void TimeStretchProcessor::setSpeed(double speed) {
    if (!impl_ || !std::isfinite(speed) || speed<0.25 || speed>2.0)
        throw std::invalid_argument("Speed must be 0.25..2.0 after prepare");
    impl_->targetSpeed.store(speed,std::memory_order_release);
    if (!impl_->workerStarted.load(std::memory_order_acquire) &&
        impl_->input.writePosition()==0 && impl_->output.writePosition()==0)
        impl_->publishedSpeed.store(speed,std::memory_order_release);
}
double TimeStretchProcessor::targetSpeed() const noexcept {
    return impl_?impl_->targetSpeed.load(std::memory_order_acquire):1.0;
}
double TimeStretchProcessor::currentSpeed() const noexcept {
    return impl_?impl_->publishedSpeed.load(std::memory_order_acquire):1.0;
}
std::size_t TimeStretchProcessor::pushInput(
    const float* const* input,std::size_t frames) noexcept {
    if (!impl_ || !input || impl_->ended.load(std::memory_order_acquire))return 0;
    for (std::size_t c=0;c<impl_->channels;++c)if (!input[c])return 0;
    const auto count=impl_->input.push(input,frames);
    impl_->inputOverruns.fetch_add(frames-count,std::memory_order_relaxed);
    const auto level=impl_->input.available();
    auto maximum=impl_->inputHighWater.load(std::memory_order_relaxed);
    while (level>maximum && !impl_->inputHighWater.compare_exchange_weak(
        maximum,level,std::memory_order_relaxed)) {}
    return count;
}
std::size_t TimeStretchProcessor::availableInputCapacity() const noexcept {
    return impl_?impl_->input.free():0;
}
std::size_t TimeStretchProcessor::process(std::size_t maxOutputFrames) noexcept {
    if (!impl_ || impl_->fault.load(std::memory_order_acquire))return 0;
    if (!impl_->workerStarted.exchange(true,std::memory_order_acq_rel))
        impl_->timeline.reset(impl_->targetSpeed.load(std::memory_order_acquire));
    const auto start=std::chrono::steady_clock::now();
    const auto limit=std::min(maxOutputFrames,impl_->maxBlock);
    std::size_t count=0;
    try {
        while (count<limit && impl_->one())++count;
    } catch (...) {
        if (impl_->faultCode.load(std::memory_order_relaxed)==0)
            impl_->faultCode.store(1,std::memory_order_release);
        impl_->fault.store(true,std::memory_order_release);
    }
    if (count<limit && !impl_->ended.load(std::memory_order_acquire) &&
        impl_->output.free()>0)
        impl_->inputUnderruns.fetch_add(1,std::memory_order_relaxed);
    impl_->workerCalls.fetch_add(1,std::memory_order_relaxed);
    impl_->processingNanoseconds.fetch_add(static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now()-start).count()),std::memory_order_relaxed);
    return count;
}
std::size_t TimeStretchProcessor::availableOutputFrames() const noexcept {
    return impl_?impl_->output.available():0;
}
std::size_t TimeStretchProcessor::pullOutput(float* const* output,
                                            std::size_t frames) noexcept {
    if (!impl_ || !output)return 0;
    for (std::size_t c=0;c<impl_->channels;++c)if (!output[c])return 0;
    const auto count=impl_->output.pull(output,frames);
    impl_->outputUnderruns.fetch_add(frames-count,std::memory_order_relaxed);
    return count;
}
void TimeStretchProcessor::signalEndOfInput() noexcept {
    if (impl_)impl_->ended.store(true,std::memory_order_release);
}
bool TimeStretchProcessor::drained() const noexcept {
    return impl_ && impl_->workerFinished.load(std::memory_order_acquire) &&
           impl_->output.available()==0 && !impl_->fault.load(std::memory_order_acquire);
}
bool TimeStretchProcessor::faulted() const noexcept {
    return impl_ && impl_->fault.load(std::memory_order_acquire);
}
ProcessorStatistics TimeStretchProcessor::statistics() const noexcept {
    ProcessorStatistics result;
    if (!impl_)return result;
    result.inputUnderrunCalls=impl_->inputUnderruns.load();
    result.outputUnderrunFrames=impl_->outputUnderruns.load();
    result.inputOverrunFrames=impl_->inputOverruns.load();
    result.inputHighWaterFrames=impl_->inputHighWater.load();
    result.outputHighWaterFrames=impl_->outputHighWater.load();
    result.processingNanoseconds=impl_->processingNanoseconds.load();
    result.workerCalls=impl_->workerCalls.load();
    result.resetCount=impl_->resetCount.load();
    result.transientEvents=impl_->publishedEvents.load();
    result.preciseAnchors=impl_->publishedAnchors.load();
    result.stretchDebtSamples=impl_->publishedDebt.load();
    result.maximumAbsoluteDebtSamples=impl_->publishedMaximumDebt.load();
    result.dspFaultCode=impl_->faultCode.load();
    return result;
}
ProcessorLatency TimeStretchProcessor::latency() const noexcept {
    return impl_?impl_->latency():ProcessorLatency{};
}
std::size_t TimeStretchProcessor::inputFifoCapacity() const noexcept {
    return impl_?inputCapacity:0;
}
std::size_t TimeStretchProcessor::outputFifoCapacity() const noexcept {
    return impl_?outputCapacity:0;
}
std::size_t TimeStretchProcessor::workingMemoryBytes() const noexcept {
    return impl_?impl_->bytes():0;
}
bool TimeStretchProcessor::transientEvent(std::uint64_t sequence,
                                         RealtimeTransientEvent& event) const noexcept {
    return impl_ && impl_->transient &&
        impl_->transient->event(sequence,event);
}
}
