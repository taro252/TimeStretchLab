#import <AVFoundation/AVFoundation.h>
#include "prototype/Phase26PlaybackPipeline.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstring>
#include <iostream>
#include <mach/mach_time.h>
#include <new>
#include <cstdlib>
#include <stdexcept>
#include <sys/resource.h>
#include <thread>
#include <vector>

namespace {
thread_local bool insideRender=false;
std::atomic<std::uint64_t> renderCppAllocations{0};
void* countedNew(std::size_t bytes,std::size_t alignment=alignof(std::max_align_t)) {
    if (insideRender) renderCppAllocations.fetch_add(1,std::memory_order_relaxed);
    void* result=nullptr;
    if (posix_memalign(&result,alignment,bytes ? bytes : 1)!=0) throw std::bad_alloc();
    return result;
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

namespace {
using Clock=std::chrono::steady_clock;
volatile std::sig_atomic_t interrupted=0;
void interrupt(int) { interrupted=1; }
struct State {
    ts::prototype::Phase26PlaybackPipeline* pipeline=nullptr;
    std::uint32_t channels=0;
    double rate=0;
    std::uint32_t numer=1,denom=1;
    std::atomic<bool> active{false},routeChanged{false};
    std::atomic<std::uint32_t> activeCallbacks{0};
    std::atomic<std::uint64_t> content{0},calls{0},silence{0};
    std::atomic<std::uint64_t> maxCallbackNs{0},deadlineMisses{0},formatErrors{0};
    std::atomic<std::uint64_t> appliedPresentationNs{0},completionPresentationNs{0};
};
struct PlaybackGuard {
    AVAudioEngine* engine;
    State* state;
    ts::prototype::Phase26PlaybackPipeline* pipeline;
    id observer;
    bool cleaned=false;
    void stop() noexcept {
        if (cleaned) return;
        cleaned=true;
        state->active.store(false,std::memory_order_release);
        if (engine.isRunning) [engine stop];
        while (state->activeCallbacks.load(std::memory_order_acquire))
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        pipeline->stop();
        if (observer) [[NSNotificationCenter defaultCenter] removeObserver:observer];
    }
    ~PlaybackGuard() { stop(); }
};
struct CpuStress {
    std::atomic<bool> stop{false};
    std::atomic<std::uint64_t> ticks{0};
    std::vector<std::thread> threads;
    explicit CpuStress(bool enabled) {
        if (enabled) for (int i=0;i<2;++i) threads.emplace_back([this] {
            while (!stop.load(std::memory_order_relaxed))
                ticks.fetch_add(1,std::memory_order_relaxed);
        });
    }
    ~CpuStress() {
        stop.store(true,std::memory_order_relaxed);
        for (auto& thread:threads) thread.join();
    }
};
OSStatus render(State* state,BOOL* isSilence,AVAudioFrameCount frames,
                AudioBufferList* buffers) noexcept {
    insideRender=true;
    state->activeCallbacks.fetch_add(1,std::memory_order_acq_rel);
    const auto start=mach_absolute_time();
    float* channel[2]={};
    bool valid=buffers->mNumberBuffers==state->channels;
    if (valid) for (std::uint32_t c=0;c<state->channels;++c) {
        auto& buffer=buffers->mBuffers[c];
        channel[c]=static_cast<float*>(buffer.mData);
        if (!channel[c] || buffer.mDataByteSize<frames*sizeof(float)) valid=false;
    }
    if (!valid) {
        for (UInt32 c=0;c<buffers->mNumberBuffers;++c)
            if (buffers->mBuffers[c].mData)
                std::memset(buffers->mBuffers[c].mData,0,buffers->mBuffers[c].mDataByteSize);
        state->formatErrors.fetch_add(1,std::memory_order_relaxed);
        *isSilence=YES;
    } else if (!state->active.load(std::memory_order_acquire)) {
        for (std::uint32_t c=0;c<state->channels;++c)
            std::memset(channel[c],0,frames*sizeof(float));
        *isSilence=YES;
    } else {
        const auto before=state->content.load(std::memory_order_relaxed);
        const auto markers=state->pipeline->realtimeMarkers();
        const auto length=markers.outputLength;
        const auto wanted=std::min<std::size_t>(frames,length>before ? length-before : 0);
        const auto received=state->pipeline->pullAudio(channel,wanted);
        for (std::uint32_t c=0;c<state->channels;++c)
            std::memset(channel[c]+wanted,0,(frames-wanted)*sizeof(float));
        state->content.store(before+received,std::memory_order_release);
        state->silence.fetch_add(wanted-received,std::memory_order_relaxed);
        state->calls.fetch_add(1,std::memory_order_relaxed);
        const auto now=mach_absolute_time();
        const auto ns=static_cast<std::uint64_t>(
            (static_cast<long double>(now)*state->numer)/state->denom);
        if (markers.appliedOutput && before<=markers.appliedOutput &&
            before+received>markers.appliedOutput)
            state->appliedPresentationNs.store(ns,std::memory_order_relaxed);
        if (markers.completionOutput && before<=markers.completionOutput &&
            before+received>markers.completionOutput)
            state->completionPresentationNs.store(ns,std::memory_order_relaxed);
        *isSilence=received==0 ? YES : NO;
    }
    const auto ticks=mach_absolute_time()-start;
    const auto ns=static_cast<std::uint64_t>(
        (static_cast<long double>(ticks)*state->numer)/state->denom);
    auto old=state->maxCallbackNs.load(std::memory_order_relaxed);
    while (old<ns && !state->maxCallbackNs.compare_exchange_weak(old,ns,std::memory_order_relaxed)) {}
    if (ns>static_cast<std::uint64_t>(std::llround(frames*1e9/state->rate)))
        state->deadlineMisses.fetch_add(1,std::memory_order_relaxed);
    state->activeCallbacks.fetch_sub(1,std::memory_order_release);
    insideRender=false;
    return noErr;
}
}

int main(int argc,char** argv) {
    if (argc<3 || argc>6) {
        std::cerr<<"Usage: phase26_play input.wav 050|075 "
                    "[switch-at-output-seconds] [max-play-seconds] [A|BCD]\n";
        return 2;
    }
    std::signal(SIGINT,interrupt);
    try {
        const std::string initialName=argv[2];
        if (initialName!="050" && initialName!="075")
            throw std::invalid_argument("Initial speed must be 050 or 075");
        const auto initial=initialName=="050" ? ts::prototype::PlaybackSpeed::Half
                                              : ts::prototype::PlaybackSpeed::ThreeQuarter;
        const auto target=initial==ts::prototype::PlaybackSpeed::Half
            ? ts::prototype::PlaybackSpeed::ThreeQuarter : ts::prototype::PlaybackSpeed::Half;
        const double switchSeconds=argc>=4 ? std::stod(argv[3]) : 3.0;
        const double maxSeconds=argc>=5 ? std::stod(argv[4]) : 0.0;
        if (switchSeconds<0 || maxSeconds<0) throw std::invalid_argument("Negative time");
        const std::string profile=argc>=6 ? argv[5] : "BCD";
        if (profile!="A" && profile!="BCD")
            throw std::invalid_argument("Unknown Phase 26 profile");
        const bool bcd=profile=="BCD";
        const std::size_t fifoFrames=bcd ? 16384 : 32768;
        const std::size_t blockFrames=bcd ? 2048 : 8192;
        const std::size_t leadLimit=bcd ? 12288 : 32768;
        const bool pollBlocked=bcd;
        const auto prepareBegin=Clock::now();
        ts::prototype::Phase26PlaybackPipeline pipeline(argv[1],initial,fifoFrames,blockFrames,
                                                        leadLimit,pollBlocked);
        const auto analysisSeconds=std::chrono::duration<double>(
            Clock::now()-prepareBegin).count();
        State state;
        state.pipeline=&pipeline;
        state.channels=static_cast<std::uint32_t>(pipeline.channels());
        state.rate=pipeline.sampleRate();
        mach_timebase_info_data_t info{};
        mach_timebase_info(&info);
        state.numer=info.numer;state.denom=info.denom;
        AVAudioEngine* engine=nil;
        AVAudioFormat* hardware=nil;
        AVAudioFormat* format=nil;
        AVAudioSourceNode* source=nil;
        id observer=nil;
        State* pointer=&state;
        @try {
            engine=[[AVAudioEngine alloc] init];
            hardware=[engine.outputNode outputFormatForBus:0];
            if (hardware.sampleRate<=0 || hardware.channelCount==0)
                throw std::runtime_error("No audio output device");
            format=[[AVAudioFormat alloc]
                initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:pipeline.sampleRate()
                channels:static_cast<AVAudioChannelCount>(pipeline.channels()) interleaved:NO];
            source=[[AVAudioSourceNode alloc] initWithFormat:format
                renderBlock:^OSStatus(BOOL* silent,const AudioTimeStamp*,
                                      AVAudioFrameCount frames,AudioBufferList* data) {
                    return render(pointer,silent,frames,data);
                }];
            [engine attachNode:source];
            [engine connect:source to:engine.mainMixerNode format:format];
            engine.mainMixerNode.outputVolume=std::getenv("PHASE25_SILENT") ? 0.0f : 0.5f;
            // The playback gain is never applied to the raw DSP FIFO.
            [engine prepare];
            observer=[[NSNotificationCenter defaultCenter]
                addObserverForName:AVAudioEngineConfigurationChangeNotification object:engine
                queue:nil usingBlock:^(NSNotification*) {
                    pointer->routeChanged.store(true,std::memory_order_release);
                }];
        } @catch (NSException* exception) {
            throw std::runtime_error([[exception description] UTF8String]);
        }
        PlaybackGuard guard{engine,&state,&pipeline,observer};
        const auto prefillBegin=Clock::now();
        pipeline.start();
        if (!pipeline.waitForPrefill(std::min<std::size_t>(
                bcd ? 8192 : 16384,pipeline.inputFrames()*2),
                                     std::chrono::seconds(120)))
            throw std::runtime_error("DSP prefill timed out");
        const auto prefill=std::chrono::duration<double>(Clock::now()-prefillBegin).count();
        state.active.store(true,std::memory_order_release);
        NSError* error=nil;
        BOOL started=NO;
        @try { started=[engine startAndReturnError:&error]; }
        @catch (NSException* exception) {
            throw std::runtime_error([[exception description] UTF8String]);
        }
        if (!started)
            throw std::runtime_error(error ? [[error description] UTF8String] : "Audio start failed");
        CpuStress stress(std::getenv("PHASE25_STRESS")!=nullptr);
        const auto playStart=Clock::now();
        const auto threshold=static_cast<std::size_t>(switchSeconds*pipeline.sampleRate());
        bool sent=false;
        std::uint64_t requestNs=0;
        std::uint64_t requestSteadyNs=0;
        std::size_t checkpoint=0;
        constexpr double checkpoints[]={180,300,600};
        while (!interrupted && !state.routeChanged.load()) {
            const auto played=state.content.load(std::memory_order_acquire);
            if (!sent && played>=threshold) {
                const auto ticks=mach_absolute_time();
                requestNs=static_cast<std::uint64_t>(
                    (static_cast<long double>(ticks)*state.numer)/state.denom);
                requestSteadyNs=static_cast<std::uint64_t>(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(
                        Clock::now().time_since_epoch()).count());
                if (pipeline.requestSpeed(target,played)!=
                    ts::prototype::Phase26RequestResult::Accepted)
                    throw std::runtime_error("Speed request rejected at control thread");
                sent=true;
            }
            if (pipeline.finished()) pipeline.rethrowWorkerError();
            if (pipeline.drained() && played>=pipeline.snapshot().outputLength) break;
            const auto elapsed=std::chrono::duration<double>(Clock::now()-playStart).count();
            if (checkpoint<3 && elapsed>=checkpoints[checkpoint]) {
                const auto progress=pipeline.snapshot();
                std::cout<<"checkpoint_seconds="<<checkpoints[checkpoint]
                         <<" presented="<<played
                         <<" fifo="<<pipeline.available()
                         <<" underrun="<<progress.underrunFrames
                         <<" deadline_misses="<<state.deadlineMisses.load()
                         <<" max_callback_ms="<<state.maxCallbackNs.load()/1e6
                         <<" max_worker_ms="<<progress.maxWorkerChunkSeconds*1000
                         <<std::endl;
                ++checkpoint;
            }
            if (maxSeconds>0 && Clock::now()-playStart>=std::chrono::duration<double>(maxSeconds)) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        const bool endDrained=pipeline.drained() &&
            state.content.load(std::memory_order_acquire)>=pipeline.snapshot().outputLength;
        if (endDrained) {
            const auto latency=std::max(0.1,engine.outputNode.presentationLatency+0.1);
            std::this_thread::sleep_for(std::chrono::duration<double>(latency));
        }
        guard.stop();
        pipeline.rethrowWorkerError();
        const auto status=pipeline.snapshot();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto userCpu=usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6;
        const auto systemCpu=usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6;
        const auto wall=std::chrono::duration<double>(Clock::now()-playStart).count();
        const auto deviceLatencyMs=engine.outputNode.presentationLatency*1000;
        std::cout<<"initial_speed="<<initialName<<'\n'
                 <<"target_speed="<<(initialName=="050" ? "075" : "050")<<'\n'
                 <<"profile="<<profile<<'\n'
                 <<"fifo_capacity_frames="<<fifoFrames<<'\n'
                 <<"lead_limit_frames="<<(leadLimit ? leadLimit : fifoFrames)<<'\n'
                 <<"dsp_block_frames="<<blockFrames<<'\n'
                 <<"prefill_seconds="<<prefill<<'\n'
                 <<"analysis_seconds="<<analysisSeconds<<'\n'
                 <<"output_device_rate="<<hardware.sampleRate<<'\n'
                 <<"wall_seconds="<<wall<<'\n'
                 <<"cpu_user_seconds="<<userCpu<<'\n'
                 <<"cpu_system_seconds="<<systemCpu<<'\n'
                 <<"device_presentation_latency_ms="<<deviceLatencyMs<<'\n'
                 <<"request_output="<<status.requestedOutput<<'\n'
                 <<"request_generation="<<status.generation<<'\n'
                 <<"plan_outcome="<<static_cast<int>(status.planOutcome)<<'\n'
                 <<"published_at_request="<<status.publishedAtPlan<<'\n'
                 <<"planning_fence="<<status.planningFence<<'\n'
                 <<"prepared_at_plan="<<status.preparedAtPlan<<'\n'
                 <<"prepared_fence="<<status.preparedFence<<'\n'
                 <<"processed_input_fence="<<status.processedInputFence<<'\n'
                 <<"first_input_at_plan="<<status.processedInputAtPlan<<'\n'
                 <<"fifo_at_plan_frames="<<status.fifoAtPlan<<'\n'
                 <<"event_protection_delay_frames="
                 <<(status.appliedOutput>=status.planningFence
                    ? status.appliedOutput-status.planningFence : 0)<<'\n'
                 <<"published_ahead_at_plan_frames="
                 <<(status.publishedAtPlan>=status.requestedOutput
                    ? status.publishedAtPlan-status.requestedOutput : 0)<<'\n'
                 <<"applied_output="<<status.appliedOutput<<'\n'
                 <<"completion_output="<<status.completionOutput<<'\n'
                 <<"request_to_apply_map_ms="
                 <<(status.appliedOutput>=status.requestedOutput
                    ? double(status.appliedOutput-status.requestedOutput)*1000/pipeline.sampleRate() : -1)<<'\n'
                 <<"map_ramp_ms="
                 <<(status.completionOutput>=status.appliedOutput
                    ? double(status.completionOutput-status.appliedOutput)*1000/pipeline.sampleRate() : -1)<<'\n'
                 <<"presented_frames="<<state.content.load()<<'\n'
                 <<"output_length="<<status.outputLength<<'\n'
                 <<"eos_drained="<<endDrained<<'\n'
                 <<"fifo_high_water="<<status.fifoHighWater<<'\n'
                 <<"fifo_rejected_writes="<<status.rejectedWrites<<'\n'
                 <<"underrun_frames="<<status.underrunFrames<<'\n'
                 <<"max_worker_chunk_ms="<<status.maxWorkerChunkSeconds*1000<<'\n'
                 <<"max_callback_ms="<<state.maxCallbackNs.load()/1e6<<'\n'
                 <<"callback_deadline_misses="<<state.deadlineMisses.load()<<'\n'
                 <<"callback_format_errors="<<state.formatErrors.load()<<'\n'
                 <<"callback_cpp_allocations="<<renderCppAllocations.load()<<'\n'
                 <<"peak_rss_mib="<<usage.ru_maxrss/1048576.0<<'\n'
                 <<"applied_callback_after_request_ms="
                 <<(state.appliedPresentationNs.load() && requestNs
                   ? (state.appliedPresentationNs.load()-requestNs)/1e6 : -1)<<'\n'
                 <<"completion_callback_after_request_ms="
                 <<(state.completionPresentationNs.load() && requestNs
                   ? (state.completionPresentationNs.load()-requestNs)/1e6 : -1)<<'\n'
                 <<"applied_estimated_speaker_after_request_ms="
                 <<(state.appliedPresentationNs.load() && requestNs
                   ? (state.appliedPresentationNs.load()-requestNs)/1e6+deviceLatencyMs : -1)<<'\n'
                 <<"request_to_plan_ms="
                 <<(status.planNs && requestSteadyNs
                   ? (status.planNs-requestSteadyNs)/1e6 : -1)<<'\n'
                 <<"control_poll_late_ms="
                 <<(status.requestedOutput>=threshold
                    ? double(status.requestedOutput-threshold)*1000/pipeline.sampleRate() : -1)<<'\n'
                 <<"control_accept_ms="
                 <<(status.acceptedNs>=status.requestNs
                    ? (status.acceptedNs-status.requestNs)/1e6 : -1)<<'\n'
                 <<"accept_to_worker_ms="
                 <<(status.workerSeenNs>=status.acceptedNs
                    ? (status.workerSeenNs-status.acceptedNs)/1e6 : -1)<<'\n'
                 <<"worker_to_plan_ms="
                 <<(status.planNs>=status.workerSeenNs
                    ? (status.planNs-status.workerSeenNs)/1e6 : -1)<<'\n'
                 <<"plan_to_applied_callback_ms="
                 <<(state.appliedPresentationNs.load() && status.planNs
                    ? (state.appliedPresentationNs.load()-requestNs)/1e6-
                      (status.planNs-requestSteadyNs)/1e6 : -1)<<'\n';
        return !sent || (maxSeconds==0 && !endDrained) ||
            status.state!=ts::prototype::Phase26RequestState::Applied ||
            status.underrunFrames || status.rejectedWrites || state.deadlineMisses ||
            state.formatErrors || renderCppAllocations.load() || state.routeChanged ? 4 : 0;
    } catch (const std::exception& exception) {
        std::cerr<<"Phase 24: "<<exception.what()<<'\n';
        return 1;
    }
}
