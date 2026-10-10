#import <AVFoundation/AVFoundation.h>
#include "audio/WavStream.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <mach/mach_time.h>
#include <new>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <thread>

namespace {
using Clock=std::chrono::steady_clock;
constexpr float playbackGain=0.5f;
constexpr std::size_t prefillFrames=16384;
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
    std::atomic<std::uint32_t> activeCallbacks{0};
    std::atomic<std::uint64_t> contentFrames{0},renderedFrames{0};
    std::atomic<std::uint64_t> silenceFrames{0},callbackCalls{0},deadlineMisses{0};
    std::atomic<std::uint64_t> maxCallbackNanoseconds{0},formatErrors{0};
    void reset(std::uint64_t target) noexcept {
        targetFrames=target;
        contentFrames.store(0);renderedFrames.store(0);silenceFrames.store(0);
        callbackCalls.store(0);deadlineMisses.store(0);maxCallbackNanoseconds.store(0);
        formatErrors.store(0);routeChanged.store(false);diagnosticStarve.store(false);
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
    std::uint64_t target=0,content=0,rendered=0,silence=0,callbacks=0;
    std::uint64_t deadlineMisses=0,maxCallbackNanoseconds=0,formatErrors=0;
    std::uint64_t cppAllocations=0;
    double wallSeconds=0,outputRate=0,presentationLatency=0,peakRSSMiB=0;
    bool routeChanged=false,interrupted=false,eosDrained=false;
};

class MacPlayer {
public:
    explicit MacPlayer(const std::filesystem::path& file)
        : input_(file),pipeline_(frozenConfig(input_)) {
        pipeline_.prepare(file);
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

    RunResult run(std::uint64_t limitFrames=0,bool forceUnderflow=false) {
        const auto target=limitFrames ? std::min<std::uint64_t>(limitFrames,pipeline_.outputFrames())
                                      : pipeline_.outputFrames();
        state_.reset(target);
        renderCppAllocations.store(0);
        pipeline_.start();
        if (!forceUnderflow) {
            const auto prefill=std::min<std::uint64_t>(prefillFrames,target);
            if (!pipeline_.waitForPrefill(prefill,std::chrono::seconds(120))) {
                stop();
                pipeline_.rethrowWorkerError();
                throw std::runtime_error("DSP prefill timed out");
            }
        }
        NSError* error=nil;
        const auto begin=Clock::now();
        state_.diagnosticStarve.store(forceUnderflow,std::memory_order_release);
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
        // Diagnostic only: suppress FIFO reads for 100 ms while the worker
        // runs, then verify that zero fill preserves the raw-content position.
        if (forceUnderflow) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            state_.diagnosticStarve.store(false,std::memory_order_release);
        }
        const auto timeout=std::chrono::duration<double>(double(target)/input_.sampleRate()+30.0);
        auto nextProgress=begin+std::chrono::seconds(30);
        while (state_.contentFrames.load(std::memory_order_acquire)<target) {
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
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        const bool completed=state_.contentFrames.load(std::memory_order_acquire)==target;
        const auto latency=engine_.outputNode.presentationLatency;
        if (completed) std::this_thread::sleep_for(std::chrono::duration<double>(std::max(0.1,latency+0.1)));
        RunResult result;
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
        rusage usage{};
        if (getrusage(RUSAGE_SELF,&usage)==0)
            result.peakRSSMiB=double(usage.ru_maxrss)/(1024.0*1024.0);
        result.routeChanged=state_.routeChanged.load();
        result.interrupted=interrupted!=0;
        stop();
        result.pipeline=pipeline_.statistics();
        result.eosDrained=pipeline_.drained();
        pipeline_.rethrowWorkerError();
        if (!completed && !result.routeChanged && !result.interrupted)
            throw std::runtime_error("Playback did not consume expected DSP frames");
        if (completed && target==pipeline_.outputFrames() && !result.eosDrained)
            throw std::runtime_error("End of stream was not fully drained");
        return result;
    }

    double inputRate() const { return input_.sampleRate(); }
    double initialOutputRate() const { return initialOutputRate_; }
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
              << "target_raw_frames=" << r.target << '\n'
              << "consumed_raw_frames=" << r.content << '\n'
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
              << "dsp_active_seconds=" << r.pipeline.dspActiveSeconds << '\n'
              << "max_worker_chunk_ms=" << r.pipeline.maxWorkerChunkSeconds*1000 << '\n'
              << "fifo_high_water_frames=" << r.pipeline.fifoHighWaterFrames << '\n'
              << "fifo_rejected_writes=" << r.pipeline.fifoRejectedWrites << '\n'
              << "fifo_underrun_calls=" << r.pipeline.underrunCalls << '\n'
              << "fifo_underrun_frames=" << r.pipeline.underrunFrames << '\n'
              << "produced_raw_frames=" << r.pipeline.producedFrames << '\n'
              << "eos_drained=" << r.eosDrained << '\n'
              << "route_changed=" << r.routeChanged << '\n'
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
    if (argc<2 || argc>3) {
        std::cerr << "Usage: phase15_play input.wav [--restart-smoke|--underflow-smoke]\n";
        return 2;
    }
    std::signal(SIGINT,interruptHandler);
    @autoreleasepool {
        try {
            MacPlayer player(argv[1]);
            if (argc==3) {
                const std::string option(argv[2]);
                if (option=="--underflow-smoke") {
                    const auto result=player.run(static_cast<std::uint64_t>(player.inputRate()*3),true);
                    print("forced_underflow",player,result);
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
