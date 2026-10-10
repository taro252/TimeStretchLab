#import <AVFoundation/AVFoundation.h>
#include "audio/WavStream.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include "dsp/Phase18PcmCache.h"
#include "dsp/Phase18SeekQueue.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
#include <mach/mach_time.h>
#include <new>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <thread>
#include <vector>

namespace {
using Clock=std::chrono::steady_clock;
constexpr float playbackGain=0.5f;
constexpr std::size_t prefillFrames=16384;
constexpr std::uint32_t seekFadeFrames=256;
volatile std::sig_atomic_t interrupted=0;
thread_local bool insideRender=false;
std::atomic<std::uint64_t> renderCppAllocations{0};
void* countedNew(std::size_t bytes,std::size_t alignment=alignof(std::max_align_t)) {
    if (insideRender) renderCppAllocations.fetch_add(1,std::memory_order_relaxed);
    void* result=nullptr;
    if (posix_memalign(&result,alignment,bytes ? bytes : 1)!=0) throw std::bad_alloc();
    return result;
}
void interruptHandler(int) { interrupted=1; }

struct RenderState {
    ts::Phase14PlaybackPipeline* pipeline=nullptr;
    std::uint64_t targetFrames=0;
    unsigned channels=0;
    double sourceRate=0;
    std::uint32_t timeNumer=1,timeDenom=1;
    std::atomic<bool> active{false},routeChanged{false},diagnosticStarve{false};
    std::atomic<int> seekFadeMode{0}; // 0=off, 1=out, 2=in; playback gain only
    std::atomic<std::uint32_t> seekFadeProgress{0};
    std::atomic<bool> seekFadeOutComplete{false};
    std::atomic<std::uint32_t> activeCallbacks{0};
    std::atomic<std::uint64_t> contentFrames{0},renderedFrames{0};
    std::atomic<std::uint64_t> silenceFrames{0},callbackCalls{0},deadlineMisses{0};
    std::atomic<std::uint64_t> maxCallbackNanoseconds{0},formatErrors{0};
    void reset(std::uint64_t target) noexcept {
        targetFrames=target;
        contentFrames.store(0);renderedFrames.store(0);silenceFrames.store(0);
        callbackCalls.store(0);deadlineMisses.store(0);maxCallbackNanoseconds.store(0);
        formatErrors.store(0);routeChanged.store(false);diagnosticStarve.store(false);
        seekFadeMode.store(0);seekFadeProgress.store(0);seekFadeOutComplete.store(false);
    }
};

// Render thread: fixed stack pointers, FIFO copy/zero fill, integer clock and
// atomic counters only. No Objective-C messages, logging, allocation or locks.
OSStatus render(RenderState* state,BOOL* isSilence,AVAudioFrameCount frames,
                AudioBufferList* buffers) noexcept {
    insideRender=true;
    state->activeCallbacks.fetch_add(1,std::memory_order_acq_rel);
    const auto begin=mach_absolute_time();
    if (buffers->mNumberBuffers!=state->channels) {
        for (UInt32 i=0;i<buffers->mNumberBuffers;++i)
            std::memset(buffers->mBuffers[i].mData,0,buffers->mBuffers[i].mDataByteSize);
        state->formatErrors.fetch_add(1,std::memory_order_relaxed);
        *isSilence=YES;
    } else {
        float* channel[2]={};
        bool valid=true;
        for (unsigned i=0;i<state->channels;++i) {
            auto& buffer=buffers->mBuffers[i];
            channel[i]=static_cast<float*>(buffer.mData);
            if (!channel[i] || buffer.mDataByteSize<frames*sizeof(float)) valid=false;
        }
        if (!valid) {
            for (UInt32 i=0;i<buffers->mNumberBuffers;++i)
                if (buffers->mBuffers[i].mData)
                    std::memset(buffers->mBuffers[i].mData,0,buffers->mBuffers[i].mDataByteSize);
            state->formatErrors.fetch_add(1,std::memory_order_relaxed);
            *isSilence=YES;
        } else if (!state->active.load(std::memory_order_acquire)) {
            for (unsigned i=0;i<state->channels;++i) std::memset(channel[i],0,frames*sizeof(float));
            *isSilence=YES;
        } else {
            const auto consumed=state->contentFrames.load(std::memory_order_relaxed);
            const auto remaining=state->targetFrames-consumed;
            const auto requested=std::min<std::uint64_t>(frames,remaining);
            const bool starve=state->diagnosticStarve.load(std::memory_order_relaxed);
            const auto received=starve ? std::size_t{0} :
                state->pipeline->pullAudio(channel,static_cast<std::size_t>(requested));
            if (starve)
                for (unsigned i=0;i<state->channels;++i)
                    std::memset(channel[i],0,requested*sizeof(float));
            const auto fadeMode=state->seekFadeMode.load(std::memory_order_acquire);
            if (fadeMode && received) {
                auto progress=state->seekFadeProgress.load(std::memory_order_relaxed);
                for (std::size_t i=0;i<received;++i) {
                    const auto step=std::min(progress,seekFadeFrames-1);
                    const float factor=fadeMode==1
                        ? float(seekFadeFrames-1-step)/float(seekFadeFrames-1)
                        : float(step)/float(seekFadeFrames-1);
                    for (unsigned c=0;c<state->channels;++c) channel[c][i]*=factor;
                    if (progress<seekFadeFrames) ++progress;
                }
                state->seekFadeProgress.store(progress,std::memory_order_release);
                if (fadeMode==1 && progress>=seekFadeFrames)
                    state->seekFadeOutComplete.store(true,std::memory_order_release);
                if (fadeMode==2 && progress>=seekFadeFrames)
                    state->seekFadeMode.store(0,std::memory_order_release);
            }
            for (unsigned i=0;i<state->channels;++i)
                std::memset(channel[i]+requested,0,(frames-requested)*sizeof(float));
            state->contentFrames.store(consumed+received,std::memory_order_release);
            state->renderedFrames.fetch_add(frames,std::memory_order_relaxed);
            state->silenceFrames.fetch_add(requested-received,std::memory_order_relaxed);
            state->callbackCalls.fetch_add(1,std::memory_order_relaxed);
            *isSilence=received==0 ? YES : NO;
        }
    }
    const auto ticks=mach_absolute_time()-begin;
    const auto nanos=static_cast<std::uint64_t>((static_cast<long double>(ticks)*state->timeNumer)/state->timeDenom);
    auto previous=state->maxCallbackNanoseconds.load(std::memory_order_relaxed);
    while (previous<nanos && !state->maxCallbackNanoseconds.compare_exchange_weak(previous,nanos,std::memory_order_relaxed)) {}
    const auto deadline=static_cast<std::uint64_t>(std::llround(double(frames)*1e9/state->sourceRate));
    if (nanos>deadline) state->deadlineMisses.fetch_add(1,std::memory_order_relaxed);
    state->activeCallbacks.fetch_sub(1,std::memory_order_release);
    insideRender=false;
    return noErr;
}

ts::StretchConfig frozenConfig(const ts::WavStreamReader& input) {
    ts::StretchConfig c;
    c.sampleRate=input.sampleRate();
    c.channels=static_cast<int>(input.channels());
    c.timeRatio=2.0;
    c.enableMultiResolution=true;
    c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;
    c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}

struct RunResult {
    ts::Phase14Statistics pipeline;
    std::uint64_t startFrame=0,target=0,content=0,rendered=0,silence=0,callbacks=0;
    std::uint64_t deadlineMisses=0,maxCallbackNanoseconds=0,formatErrors=0;
    std::uint64_t cppAllocations=0;
    double wallSeconds=0,outputRate=0,presentationLatency=0,peakRSSMiB=0,seekWarmupSeconds=0;
    double cacheValidationSeconds=0,pcmPrefillSeconds=0,controlSwitchSeconds=0;
    double fadeInSeconds=0,fadeOutWaitSeconds=0,engineRestartSeconds=0,cacheGenerationSeconds=0;
    std::uint64_t cacheBytes=0;
    std::string source="dsp_stream";
    std::string cacheError;
    bool routeChanged=false,interrupted=false,eosDrained=false,seekInterrupted=false;
};

class MacPlayer {
public:
    explicit MacPlayer(const std::filesystem::path& file,
                       const std::filesystem::path& cacheDirectory={},bool cacheEnabled=true)
        : input_(file),pipeline_(frozenConfig(input_)) {
        pipeline_.prepare(file);
        if (cacheEnabled) cache_=std::make_unique<ts::Phase18PcmCache>(file,
            cacheDirectory.empty() ? std::filesystem::current_path()/"results/phase18/cache"
                                   : cacheDirectory,frozenConfig(input_));
        state_.pipeline=&pipeline_;
        state_.channels=static_cast<unsigned>(input_.channels());
        state_.sourceRate=input_.sampleRate();
        mach_timebase_info_data_t info{};
        mach_timebase_info(&info);
        state_.timeNumer=info.numer;
        state_.timeDenom=info.denom;
        @try {
            engine_=[[AVAudioEngine alloc] init];
            AVAudioFormat* hardware=[engine_.outputNode outputFormatForBus:0];
            if (hardware.sampleRate<=0 || hardware.channelCount==0)
                throw std::runtime_error("No enabled audio output device");
            initialOutputRate_=hardware.sampleRate;
            AVAudioFormat* format=[[AVAudioFormat alloc] initWithCommonFormat:AVAudioPCMFormatFloat32
                sampleRate:input_.sampleRate() channels:static_cast<AVAudioChannelCount>(input_.channels())
                interleaved:NO];
            if (!format) throw std::runtime_error("Cannot create source audio format");
            RenderState* state=&state_;
            source_=[[AVAudioSourceNode alloc] initWithFormat:format renderBlock:^OSStatus(
                BOOL* isSilence,const AudioTimeStamp*,AVAudioFrameCount frames,AudioBufferList* data) {
                return render(state,isSilence,frames,data);
            }];
            [engine_ attachNode:source_];
            [engine_ connect:source_ to:engine_.mainMixerNode format:format];
            engine_.mainMixerNode.outputVolume=playbackGain;
            [engine_ prepare];
            observer_=[[NSNotificationCenter defaultCenter]
                addObserverForName:AVAudioEngineConfigurationChangeNotification object:engine_
                queue:nil usingBlock:^(NSNotification*) { state->routeChanged.store(true,std::memory_order_release); }];
        } @catch (NSException* error) {
            throw std::runtime_error([[error description] UTF8String]);
        }
    }

    ~MacPlayer() {
        stop();
        if (observer_) [[NSNotificationCenter defaultCenter] removeObserver:observer_];
    }

    RunResult run(std::uint64_t limitFrames=0,bool forceUnderflow=false,
                  std::uint64_t startFrame=0,std::uint64_t seekAfterFrames=0,
                  const std::function<bool()>& superseded={}) {
        if (startFrame>=pipeline_.outputFrames()) throw std::out_of_range("Seek past end of output");
        const auto remaining=pipeline_.outputFrames()-startFrame;
        const auto target=limitFrames ? std::min<std::uint64_t>(limitFrames,remaining) : remaining;
        state_.reset(target);
        cacheStartError_.clear();
        renderCppAllocations.store(0);
        const auto seekBegin=Clock::now();
        double cacheValidation=0;
        std::string source="dsp_stream";
        if (startFrame) {
            std::optional<std::filesystem::path> valid;
            if (cache_) valid=cache_->validPath(&cacheValidation);
            if (superseded && superseded()) throw ts::SeekSuperseded{};
            if (valid) {
                try {
                    pipeline_.startFromCache(*valid,startFrame,
                        std::min<std::uint64_t>(prefillFrames,target),std::chrono::seconds(120),superseded);
                    source="pcm_cache";
                } catch (const ts::SeekSuperseded&) {
                    throw;
                } catch (...) {
                    pipeline_.stop();
                    source="dsp_fallback_after_cache_error";
                    pipeline_.startAtOutputFrame(startFrame,
                        std::min<std::uint64_t>(prefillFrames,target),std::chrono::seconds(120),superseded);
                }
            } else {
                source="dsp_fallback_cache_miss";
                pipeline_.startAtOutputFrame(startFrame,
                    std::min<std::uint64_t>(prefillFrames,target),std::chrono::seconds(120),superseded);
            }
            if (cache_ && source!="pcm_cache") {
                try {cache_->beginGeneration();}
                catch (const std::exception& error) {cacheStartError_=error.what();}
            }
        } else pipeline_.start();
        if (!forceUnderflow) {
            const auto prefill=std::min<std::uint64_t>(prefillFrames,target);
            if (!startFrame && !pipeline_.waitForPrefill(prefill,std::chrono::seconds(120))) {
                stop();
                pipeline_.rethrowWorkerError();
                throw std::runtime_error("DSP prefill timed out");
            }
        }
        const auto seekWarmup=std::chrono::duration<double>(Clock::now()-seekBegin).count();
        if (!startFrame && cache_) {
            try {cache_->beginGeneration();}
            catch (const std::exception& error) {cacheStartError_=error.what();}
        }
        NSError* error=nil;
        const auto begin=Clock::now();
        state_.diagnosticStarve.store(forceUnderflow,std::memory_order_release);
        if (startFrame) state_.seekFadeMode.store(2,std::memory_order_release);
        state_.active.store(true,std::memory_order_release);
        bool started=false;
        @try { started=[engine_ startAndReturnError:&error]; }
        @catch (NSException* exception) {
            stop();
            throw std::runtime_error([[exception description] UTF8String]);
        }
        if (!started) {
            stop();
            throw std::runtime_error(error ? [[error description] UTF8String] : "AVAudioEngine start failed");
        }
        const auto engineRestart=std::chrono::duration<double>(Clock::now()-begin).count();
        // Diagnostic only: suppress FIFO reads for 100 ms while the worker
        // runs, then verify that zero fill preserves the raw-content position.
        if (forceUnderflow) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            state_.diagnosticStarve.store(false,std::memory_order_release);
        }
        const auto timeout=std::chrono::duration<double>(double(target)/input_.sampleRate()+30.0);
        auto nextProgress=begin+std::chrono::seconds(30);
        bool seekInterrupted=false,fadeRequested=false;
        auto fadeRequestedAt=Clock::time_point{};
        double fadeOutWait=0;
        while (state_.contentFrames.load(std::memory_order_acquire)<target) {
            if (!fadeRequested && ((seekAfterFrames &&
                state_.contentFrames.load(std::memory_order_acquire)>=seekAfterFrames) ||
                (superseded && superseded()))) {
                state_.seekFadeProgress.store(0,std::memory_order_relaxed);
                state_.seekFadeOutComplete.store(false,std::memory_order_relaxed);
                state_.seekFadeMode.store(1,std::memory_order_release);
                fadeRequested=true;
                fadeRequestedAt=Clock::now();
            }
            if (fadeRequested && state_.seekFadeOutComplete.load(std::memory_order_acquire)) {
                fadeOutWait=std::chrono::duration<double>(Clock::now()-fadeRequestedAt).count();
                seekInterrupted=true;
                break;
            }
            if (interrupted || state_.routeChanged.load(std::memory_order_acquire) ||
                state_.formatErrors.load(std::memory_order_relaxed)) break;
            if (Clock::now()-begin>timeout) break;
            if (pipeline_.workerFinished() && pipeline_.availableOutputFrames()==0 &&
                state_.contentFrames.load()<target && state_.activeCallbacks.load()==0) {
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
                if (state_.contentFrames.load()<target && state_.activeCallbacks.load()==0) break;
            }
            if (Clock::now()>=nextProgress) {
                std::cerr << "progress_seconds=" << state_.contentFrames.load()/input_.sampleRate()
                          << " underrun_frames=" << pipeline_.statistics().underrunFrames << '\n';
                nextProgress+=std::chrono::seconds(30);
            }
            std::this_thread::sleep_for(seekAfterFrames ? std::chrono::milliseconds(1)
                                                       : std::chrono::milliseconds(20));
        }
        const bool completed=state_.contentFrames.load(std::memory_order_acquire)==target;
        const auto latency=engine_.outputNode.presentationLatency;
        if (completed) std::this_thread::sleep_for(std::chrono::duration<double>(std::max(0.1,latency+0.1)));
        RunResult result;
        result.startFrame=startFrame;
        result.target=target;
        result.content=state_.contentFrames.load();
        result.rendered=state_.renderedFrames.load();
        result.silence=state_.silenceFrames.load();
        result.callbacks=state_.callbackCalls.load();
        result.deadlineMisses=state_.deadlineMisses.load();
        result.maxCallbackNanoseconds=state_.maxCallbackNanoseconds.load();
        result.formatErrors=state_.formatErrors.load();
        result.cppAllocations=renderCppAllocations.load();
        result.wallSeconds=std::chrono::duration<double>(Clock::now()-begin).count();
        result.outputRate=[[engine_.outputNode outputFormatForBus:0] sampleRate];
        result.presentationLatency=latency;
        result.seekWarmupSeconds=seekWarmup;
        result.cacheValidationSeconds=cacheValidation;
        result.pcmPrefillSeconds=source=="pcm_cache" ? pipeline_.statistics().prefillSeconds : 0;
        result.controlSwitchSeconds=std::max(0.0,seekWarmup-cacheValidation-result.pcmPrefillSeconds);
        result.fadeInSeconds=startFrame ? double(seekFadeFrames)/input_.sampleRate() : 0;
        result.fadeOutWaitSeconds=fadeOutWait;
        result.engineRestartSeconds=engineRestart;
        result.source=source;
        result.cacheError=cacheStartError_;
        if (cache_) {
            result.cacheGenerationSeconds=cache_->generationSeconds();
            if (cache_->generationFinished() && !cache_->generationError().empty())
                result.cacheError=cache_->generationError();
            std::error_code ignored;
            result.cacheBytes=std::filesystem::file_size(cache_->cachePath(),ignored);
            if (ignored) result.cacheBytes=0;
        }
        result.seekInterrupted=seekInterrupted;
        rusage usage{};
        if (getrusage(RUSAGE_SELF,&usage)==0)
            result.peakRSSMiB=double(usage.ru_maxrss)/(1024.0*1024.0);
        result.routeChanged=state_.routeChanged.load();
        result.interrupted=interrupted!=0;
        stop();
        result.pipeline=pipeline_.statistics();
        result.eosDrained=pipeline_.drained();
        pipeline_.rethrowWorkerError();
        if (!completed && !result.routeChanged && !result.interrupted && !result.seekInterrupted)
            throw std::runtime_error("Playback did not consume expected DSP frames");
        if (completed && startFrame==0 && target==pipeline_.outputFrames() && !result.eosDrained)
            throw std::runtime_error("End of stream was not fully drained");
        return result;
    }

    RunResult runLatest(ts::Phase18SeekQueue& requests,std::uint64_t limitFrames=0) {
        for (;;) {
            const auto [version,outputFrame]=requests.latest();
            try {
                auto result=run(limitFrames,false,outputFrame,0,
                    [&requests,version] { return requests.superseded(version); });
                if (!requests.superseded(version)) return result;
            } catch (const ts::SeekSuperseded&) {
                pipeline_.stop();
            }
        }
    }

    double inputRate() const { return input_.sampleRate(); }
    double initialOutputRate() const { return initialOutputRate_; }
    std::size_t inputFrames() const { return pipeline_.inputFrames(); }
    std::size_t outputFrames() const { return pipeline_.outputFrames(); }
    std::size_t outputFrameForInputFrame(std::size_t frame) const {
        return pipeline_.outputFrameForInputFrame(frame);
    }
private:
    void stop() noexcept {
        state_.active.store(false,std::memory_order_release);
        if (engine_ && engine_.isRunning) [engine_ stop];
        while (state_.activeCallbacks.load(std::memory_order_acquire)!=0)
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        pipeline_.stop();
    }
    ts::WavStreamReader input_;
    ts::Phase14PlaybackPipeline pipeline_;
    std::unique_ptr<ts::Phase18PcmCache> cache_;
    std::string cacheStartError_;
    RenderState state_;
    AVAudioEngine* engine_=nil;
    AVAudioSourceNode* source_=nil;
    id observer_=nil;
    double initialOutputRate_=0;
};

void print(const char* name,const MacPlayer& player,const RunResult& r) {
    std::cout << "name=" << name << '\n'
              << "source_sample_rate=" << player.inputRate() << '\n'
              << "output_sample_rate_start=" << player.initialOutputRate() << '\n'
              << "output_sample_rate_end=" << r.outputRate << '\n'
              << "headroom_gain=" << playbackGain << '\n'
              << "seek_playback_fade_frames=" << seekFadeFrames << '\n'
              << "start_raw_frame=" << r.startFrame << '\n'
              << "target_raw_frames=" << r.target << '\n'
              << "consumed_raw_frames=" << r.content << '\n'
              << "absolute_raw_frame=" << r.startFrame+r.content << '\n'
              << "rendered_frames=" << r.rendered << '\n'
              << "inserted_silence_frames=" << r.silence << '\n'
              << "callback_calls=" << r.callbacks << '\n'
              << "callback_deadline_misses=" << r.deadlineMisses << '\n'
              << "max_callback_ms=" << r.maxCallbackNanoseconds/1e6 << '\n'
              << "callback_format_errors=" << r.formatErrors << '\n'
              << "callback_cpp_allocations=" << r.cppAllocations << '\n'
              << "output_presentation_latency_ms=" << r.presentationLatency*1000 << '\n'
              << "peak_rss_mib=" << r.peakRSSMiB << '\n'
              << "playback_wall_seconds=" << r.wallSeconds << '\n'
              << "analysis_seconds=" << r.pipeline.analysisSeconds << '\n'
              << "prefill_seconds=" << r.pipeline.prefillSeconds << '\n'
              << "seek_warmup_seconds=" << r.seekWarmupSeconds << '\n'
              << "raw_source=" << r.source << '\n'
              << "cache_validation_seconds=" << r.cacheValidationSeconds << '\n'
              << "pcm_prefill_seconds=" << r.pcmPrefillSeconds << '\n'
              << "control_switch_seconds=" << r.controlSwitchSeconds << '\n'
              << "playback_fade_in_nominal_seconds=" << r.fadeInSeconds << '\n'
              << "playback_fade_out_wait_seconds=" << r.fadeOutWaitSeconds << '\n'
              << "audio_engine_restart_seconds=" << r.engineRestartSeconds << '\n'
              << "cache_generation_seconds=" << r.cacheGenerationSeconds << '\n'
              << "cache_bytes=" << r.cacheBytes << '\n'
              << "cache_error=" << r.cacheError << '\n'
              << "dsp_active_seconds=" << r.pipeline.dspActiveSeconds << '\n'
              << "max_worker_chunk_ms=" << r.pipeline.maxWorkerChunkSeconds*1000 << '\n'
              << "fifo_high_water_frames=" << r.pipeline.fifoHighWaterFrames << '\n'
              << "fifo_rejected_writes=" << r.pipeline.fifoRejectedWrites << '\n'
              << "fifo_underrun_calls=" << r.pipeline.underrunCalls << '\n'
              << "fifo_underrun_frames=" << r.pipeline.underrunFrames << '\n'
              << "produced_raw_frames=" << r.pipeline.producedFrames << '\n'
              << "eos_drained=" << r.eosDrained << '\n'
              << "route_changed=" << r.routeChanged << '\n'
              << "seek_interrupted=" << r.seekInterrupted << '\n'
              << "interrupted=" << r.interrupted << '\n';
}
}

void* operator new(std::size_t n) { return countedNew(n); }
void* operator new[](std::size_t n) { return countedNew(n); }
void* operator new(std::size_t n,std::align_val_t a) { return countedNew(n,static_cast<std::size_t>(a)); }
void* operator new[](std::size_t n,std::align_val_t a) { return countedNew(n,static_cast<std::size_t>(a)); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p,std::size_t) noexcept { std::free(p); }
void operator delete[](void* p,std::size_t) noexcept { std::free(p); }
void operator delete(void* p,std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p,std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p,std::size_t,std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p,std::size_t,std::align_val_t) noexcept { std::free(p); }

int main(int argc,char** argv) {
    if (argc<2) {
        std::cerr << "Usage: phase15_play input.wav [action] [--cache-dir=PATH] [--no-cache]\n";
        return 2;
    }
    std::signal(SIGINT,interruptHandler);
    @autoreleasepool {
        try {
            std::string option;
            std::filesystem::path cacheDirectory;
            bool cacheEnabled=true;
            for (int i=2;i<argc;++i) {
                const std::string argument(argv[i]);
                if (argument=="--no-cache") cacheEnabled=false;
                else if (argument.rfind("--cache-dir=",0)==0)
                    cacheDirectory=argument.substr(12);
                else if (option.empty()) option=argument;
                else throw std::invalid_argument("Only one playback action is supported");
            }
            if (option=="--cache-generate-only") {
                if (!cacheEnabled) throw std::invalid_argument("Cache is disabled");
                ts::WavStreamReader input(argv[1]);
                ts::Phase18PcmCache cache(argv[1],cacheDirectory.empty() ?
                    std::filesystem::current_path()/"results/phase18/cache" : cacheDirectory,
                    frozenConfig(input));
                cache.beginGeneration();cache.wait();
                if (!cache.generationError().empty()) throw std::runtime_error(cache.generationError());
                double validation=0;
                const auto ready=cache.validPath(&validation);
                if (!ready) throw std::runtime_error("Generated cache invalid");
                std::cout << "cache_path=" << ready->string() << '\n'
                          << "cache_key=" << cache.key() << '\n'
                          << "cache_bytes=" << std::filesystem::file_size(*ready) << '\n'
                          << "cache_generation_seconds=" << cache.generationSeconds() << '\n'
                          << "cache_validation_seconds=" << validation << '\n';
                return 0;
            }
            MacPlayer player(argv[1],cacheDirectory,cacheEnabled);
            if (!option.empty()) {
                if (option.rfind("--seek-input-frame=",0)==0) {
                    const auto inputFrame=std::stoull(option.substr(19));
                    const auto outputFrame=player.outputFrameForInputFrame(inputFrame);
                    const auto result=player.run(0,false,outputFrame);
                    print("stopped_seek",player,result);
                    return result.routeChanged || result.interrupted ? 3 : 0;
                }
                if (option.rfind("--seek-live=",0)==0) {
                    const auto spec=option.substr(12);
                    const auto delimiter=spec.find(':');
                    if (delimiter==std::string::npos) throw std::invalid_argument("Seek needs AFTER:TARGET");
                    const auto afterFrame=std::stoull(spec.substr(0,delimiter));
                    const auto inputFrame=std::stoull(spec.substr(delimiter+1));
                    if (!afterFrame) throw std::invalid_argument("Seek trigger must be after sample zero");
                    const auto outputFrame=player.outputFrameForInputFrame(inputFrame);
                    const auto before=player.run(0,false,0,afterFrame);
                    print("before_live_seek",player,before);
                    if (!before.seekInterrupted) return 4;
                    const auto after=player.run(0,false,outputFrame);
                    print("after_live_seek",player,after);
                    return after.routeChanged || after.interrupted ? 3 : 0;
                }
                if (option.rfind("--seek-burst=",0)==0) {
                    const auto spec=option.substr(13);
                    const auto delimiter=spec.find(':');
                    if (delimiter==std::string::npos)
                        throw std::invalid_argument("Seek burst needs AFTER:INPUT1,INPUT2,...");
                    const auto afterFrame=std::stoull(spec.substr(0,delimiter));
                    if (!afterFrame) throw std::invalid_argument("Seek burst trigger is zero");
                    std::vector<std::size_t> targets;
                    std::size_t from=delimiter+1;
                    for (;;) {
                        const auto comma=spec.find(',',from);
                        targets.push_back(player.outputFrameForInputFrame(
                            std::stoull(spec.substr(from,comma==std::string::npos ? comma : comma-from))));
                        if (comma==std::string::npos) break;
                        from=comma+1;
                    }
                    if (targets.size()<2) throw std::invalid_argument("Seek burst needs at least 2 targets");
                    const auto before=player.run(0,false,0,afterFrame);
                    print("before_seek_burst",player,before);
                    if (!before.seekInterrupted) return 4;
                    ts::Phase18SeekQueue requests;
                    requests.post(targets.front());
                    std::thread poster([&] {
                        for (std::size_t i=1;i<targets.size();++i) {
                            std::this_thread::sleep_for(std::chrono::milliseconds(5));
                            requests.post(targets[i]);
                        }
                    });
                    RunResult after;
                    try { after=player.runLatest(requests,static_cast<std::uint64_t>(player.inputRate())); }
                    catch (...) { poster.join();throw; }
                    poster.join();
                    if (after.startFrame!=targets.back())
                        after=player.run(static_cast<std::uint64_t>(player.inputRate()),false,targets.back());
                    print("after_seek_burst",player,after);
                    return after.startFrame==targets.back() && after.content==after.target ? 0 : 4;
                }
                if (option=="--underflow-smoke") {
                    const auto result=player.run(static_cast<std::uint64_t>(player.inputRate()*3),true);
                    print("forced_underflow",player,result);
                    return result.silence>0 && result.content==result.target ? 0 : 4;
                }
                if (option=="--seek-smoke") {
                    const auto second=static_cast<std::uint64_t>(player.inputRate());
                    const auto before=player.run(0,false,0,second);
                    print("before_live_seek",player,before);
                    const auto middleFrame=player.outputFrameForInputFrame(player.inputFrames()/2);
                    const auto middle=player.run(second*2,false,middleFrame);
                    print("after_live_seek",player,middle);
                    const auto nearEnd=player.run(second,false,player.outputFrames()-second);
                    print("stopped_seek_near_end",player,nearEnd);
                    return before.seekInterrupted && middle.content==middle.target &&
                        nearEnd.content==nearEnd.target ? 0 : 4;
                }
                if (option=="--seek-underflow-smoke") {
                    const auto middle=player.outputFrameForInputFrame(player.inputFrames()/2);
                    const auto result=player.run(static_cast<std::uint64_t>(player.inputRate()*2),true,middle);
                    print("seek_forced_underflow",player,result);
                    return result.silence>0 && result.content==result.target ? 0 : 4;
                }
                if (option!="--restart-smoke") throw std::invalid_argument("Unknown option");
                const auto first=player.run(static_cast<std::uint64_t>(player.inputRate()));
                print("first",player,first);
                if (first.routeChanged || first.interrupted) return 3;
                const auto second=player.run(static_cast<std::uint64_t>(player.inputRate()*3));
                print("restart",player,second);
                return second.routeChanged || second.interrupted ? 3 : 0;
            }
            const auto result=player.run();
            print("full",player,result);
            return result.routeChanged || result.interrupted ? 3 : 0;
        } catch (const std::exception& error) {
            std::cerr << "Phase 15: " << error.what() << '\n';
            return 1;
        }
    }
}
