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
        generated_=0;
        current_=rampTarget_=speed;
        rampStep_=0;
        rampRemaining_=0;
    }
    double current() const noexcept {return current_;}
    double atInput(std::size_t sample,double target) noexcept {
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
                if (--rampRemaining_==0) current_=rampTarget_;
            }
            positions_[next%mapCapacity]=positions_[generated_%mapCapacity]+
                midHop/current_;
            generated_=next;
        }
        const double u=double(sample%midHop)/midHop;
        return positions_[frame%mapCapacity]*(1-u)+
               positions_[(frame+1)%mapCapacity]*u;
    }
private:
    double rate_,current_=1,rampTarget_=1,rampStep_=0;
    std::array<double,mapCapacity> positions_{};
    std::size_t generated_=0,rampRemaining_=0;
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
        long long startAt(std::size_t frame) noexcept {
            const auto inputSample=frame*hop;
            return std::llround(parent.timeline.atInput(inputSample,
                parent.targetSpeed.load(std::memory_order_relaxed)));
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
            if (channels==2) {
                for (std::size_t k=0;k<combined.size();++k)
                    combined[k]={std::hypot(std::abs(inputSpectra[0][k]),
                                            std::abs(inputSpectra[1][k])),0};
                sharedPeaks.analyzePeaks(combined.data(),combined.size());
                const auto& owners=sharedPeaks.ownerPeak();
                for (std::size_t c=0;c<channels;++c)
                    vocoders[c].process(inputSpectra[c].data(),outputSpectra[c].data(),
                        delta,false,false,1.0f,&owners);
                coherence.process(inputSpectra[0].data(),inputSpectra[1].data(),
                    outputSpectra[0].data(),outputSpectra[1].data(),
                    vocoders[0],vocoders[1],owners);
            } else vocoders[0].process(inputSpectra[0].data(),outputSpectra[0].data(),
                                      delta);
            for (std::size_t c=0;c<channels;++c) {
                stft.synthesize(outputSpectra[c].data(),synthesized.data());
                olas[c].add(synthesized.data(),stft.window().data(),size,start);
            }
            previousStart=start;
            ++nextFrame;
        }
        bool get(std::size_t channel,std::size_t index,float& value) {
            if (parent.haveFinal && index>=parent.finalLength) {value=0;return true;}
            while (produced<=index) {
                const auto absolute=produced+padding;
                while (startAt(nextFrame)<=static_cast<long long>(absolute)) {
                    if (parent.ended.load(std::memory_order_acquire)) {
                        const auto length=parent.input.writePosition();
                        const auto frameCount=(length+padding+hop-1)/hop+1;
                        if (nextFrame>=frameCount)break;
                    }
                    if (!frameReady()) return false;
                    processFrame(startAt(nextFrame));
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
    MultiResolutionCrossover filters;
    Resolution low,mid;
    std::vector<std::unique_ptr<LiveFIR>> fir;
    std::atomic<double> targetSpeed{1.0},publishedSpeed{1.0};
    std::atomic<bool> ended{false},fault{false},workerStarted{false};
    std::atomic<bool> workerFinished{false};
    std::atomic<std::uint64_t> inputUnderruns{0},outputUnderruns{0};
    std::atomic<std::uint64_t> inputOverruns{0},inputHighWater{0},outputHighWater{0};
    std::atomic<std::uint64_t> processingNanoseconds{0},workerCalls{0},resetCount{0};
    std::size_t produced=0,finalLength=0;
    bool haveFinal=false;
    Impl(double sampleRate,std::size_t count,std::size_t block)
        :rate(sampleRate),channels(count),maxBlock(block),
         input(count,inputCapacity),output(count,outputCapacity),timeline(sampleRate),
         filters(sampleRate,250.0),low(*this,8192,2048),mid(*this,4096,1024) {
        fir.reserve(channels);
        for (std::size_t c=0;c<channels;++c)
            fir.emplace_back(std::make_unique<LiveFIR>(filters.lowFilter()));
    }
    void reset() noexcept {
        input.reset();output.reset();
        timeline.reset(targetSpeed.load(std::memory_order_relaxed));
        publishedSpeed.store(timeline.current(),std::memory_order_release);
        low.reset();mid.reset();
        for (auto& item:fir)item->reset();
        ended.store(false,std::memory_order_release);
        fault.store(false,std::memory_order_release);
        workerStarted.store(false,std::memory_order_release);
        workerFinished.store(false,std::memory_order_release);
        produced=finalLength=0;haveFinal=false;
        inputUnderruns.store(0);outputUnderruns.store(0);inputOverruns.store(0);
        inputHighWater.store(0);outputHighWater.store(0);
        processingNanoseconds.store(0);workerCalls.store(0);
        resetCount.fetch_add(1,std::memory_order_relaxed);
    }
    void releaseInput() noexcept {
        const auto consumed=std::min(low.nextNeededInput(),mid.nextNeededInput());
        input.releaseThrough(std::min(consumed,input.writePosition()));
    }
    bool one() {
        if (ended.load(std::memory_order_acquire) && !haveFinal) {
            finalLength=static_cast<std::size_t>(std::llround(timeline.atInput(
                input.writePosition(),targetSpeed.load(std::memory_order_relaxed))));
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
        return true;
    }
    ProcessorLatency latency() const noexcept {
        ProcessorLatency result;
        // First 2048-point FIR block needs output samples 0..2047.
        const double speed=targetSpeed.load(std::memory_order_relaxed);
        const auto furthestLowFrame=static_cast<std::size_t>(
            std::floor((2047.0+4096.0)*speed/2048.0));
        result.startupInputFrames=furthestLowFrame*2048+4096;
        return result;
    }
    std::size_t bytes() const noexcept {
        std::size_t result=input.bytes()+output.bytes()+low.bytes()+mid.bytes();
        for (const auto& item:fir)result+=item->bytes();
        return result+filters.workingMemoryBytes();
    }
};

TimeStretchProcessor::TimeStretchProcessor()=default;
TimeStretchProcessor::~TimeStretchProcessor()=default;
void TimeStretchProcessor::prepare(double sampleRate,int channels,std::size_t maxBlockSize) {
    if (!std::isfinite(sampleRate) || sampleRate<8000 || sampleRate>192000 ||
        (channels!=1 && channels!=2) || maxBlockSize<1 || maxBlockSize>16384)
        throw std::invalid_argument("Invalid real-time processor format");
    impl_=std::make_unique<Impl>(sampleRate,static_cast<std::size_t>(channels),maxBlockSize);
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
    } catch (...) {impl_->fault.store(true,std::memory_order_release);}
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
}
