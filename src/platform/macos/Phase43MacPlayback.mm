#import <AVFoundation/AVFoundation.h>
#include "prototype/Phase39PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstring>
#include <fstream>
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
struct ScheduledSpeed { std::size_t outputFrame; ts::prototype::Phase39Speed speed; };
std::vector<ScheduledSpeed> readSchedule(const char* path,std::uint32_t rate) {
    if (std::string(path)=="-") return {};
    std::ifstream file(path);
    if (!file) throw std::runtime_error("Cannot open speed schedule");
    std::vector<ScheduledSpeed> result;
    std::string line;
    while (std::getline(file,line)) {
        if (line.empty() || line[0]=='#' || line=="output_seconds,target_speed") continue;
        const auto comma=line.find(',');
        if (comma==std::string::npos) throw std::invalid_argument("Invalid schedule row");
        const auto seconds=std::stod(line.substr(0,comma));
        const auto speed=ts::prototype::Phase39Speed::fromDouble(
            std::stod(line.substr(comma+1)));
        if (!std::isfinite(seconds) || seconds<0 ||
            (!result.empty() &&
             std::llround(seconds*rate)<=static_cast<long long>(result.back().outputFrame)))
            throw std::invalid_argument("Schedule positions must increase");
        result.push_back({static_cast<std::size_t>(std::llround(seconds*rate)),speed});
    }
    return result;
}
volatile std::sig_atomic_t interrupted=0;
void interrupt(int) { interrupted=1; }
struct State {
    ts::prototype::Phase39PlaybackPipeline* pipeline=nullptr;
    std::uint32_t channels=0;
    double rate=0;
    std::uint32_t numer=1,denom=1;
    std::atomic<bool> active{false},routeChanged{false};
    std::atomic<std::uint32_t> activeCallbacks{0};
    std::atomic<std::uint64_t> content{0},presentationFrames{0},calls{0},silence{0};
    std::atomic<std::uint64_t> maxCallbackNs{0},deadlineMisses{0},formatErrors{0};
    std::atomic<std::uint64_t> appliedPresentationNs{0},completionPresentationNs{0};
    std::atomic<std::uint64_t> appliedPresentationGeneration{0},
        completionPresentationGeneration{0};
};
struct PlaybackGuard {
    AVAudioEngine* engine;
    State* state;
    ts::prototype::Phase39PlaybackPipeline* pipeline;
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
        state->presentationFrames.fetch_add(wanted,std::memory_order_relaxed);
        state->silence.fetch_add(wanted-received,std::memory_order_relaxed);
        state->calls.fetch_add(1,std::memory_order_relaxed);
        const auto now=mach_absolute_time();
        const auto ns=static_cast<std::uint64_t>(
            (static_cast<long double>(now)*state->numer)/state->denom);
        if (markers.appliedOutput && before<=markers.appliedOutput &&
            before+received>markers.appliedOutput) {
            state->appliedPresentationNs.store(ns,std::memory_order_relaxed);
            state->appliedPresentationGeneration.store(markers.generation,
                std::memory_order_release);
        }
        if (markers.completionOutput && before<=markers.completionOutput &&
            before+received>markers.completionOutput) {
            state->completionPresentationNs.store(ns,std::memory_order_relaxed);
            state->completionPresentationGeneration.store(markers.generation,
                std::memory_order_release);
        }
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
    if (argc<3 || argc>5) {
        std::cerr<<"Usage: phase43_play input.wav initial_speed "
                    "[schedule.csv|-] [max-play-seconds]\n";
        return 2;
    }
    std::signal(SIGINT,interrupt);
    try {
        const auto initial=ts::prototype::Phase39Speed::fromDouble(std::stod(argv[2]));
        const std::string initialName=argv[2];
        const double maxSeconds=argc>=5 ? std::stod(argv[4]) : 0.0;
        if (!std::isfinite(maxSeconds) || maxSeconds<0)
            throw std::invalid_argument("Invalid playback duration");
        constexpr std::size_t fifoFrames=16384,blockFrames=2048,leadLimit=12288;
        const auto prepareBegin=Clock::now();
        ts::prototype::Phase39PlaybackPipeline pipeline(
            argv[1],initial,fifoFrames,blockFrames,leadLimit,
            ts::prototype::Phase39Planning::C,
            ts::prototype::Phase39DensityDiagnostic::SafeGuarded,
            std::getenv("PHASE43_PROFILE")!=nullptr);
        const auto schedule=readSchedule(argc>=4 ? argv[3] : "-",pipeline.sampleRate());
        const auto changeCount=schedule.size();
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
            engine.mainMixerNode.outputVolume=std::getenv("PHASE43_SILENT") ? 0.0f : 0.5f;
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
                8192,static_cast<std::size_t>(std::llround(
                    pipeline.inputFrames()*initial.timeRatio()))),
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
        CpuStress stress(std::getenv("PHASE43_STRESS")!=nullptr);
        const auto playStart=Clock::now();
        const bool continueRejected=std::getenv("PHASE43_REJECT_POLICY") &&
            std::strcmp(std::getenv("PHASE43_REJECT_POLICY"),"continue")==0;
        const bool forceRejectFirst=std::getenv("PHASE44_FORCE_REJECT_FIRST")!=nullptr;
        std::size_t sent=0,observed=0,rejected=0,cancelled=0,active=changeCount;
        bool strictFailure=false;
        std::vector<double> applyLatencyMs(changeCount,-1),completionLatencyMs(changeCount,-1);
        std::vector<std::uint64_t> requestMachNs(changeCount,0),
            requestGenerations(changeCount,0);
        std::vector<std::string> requestStates(changeCount,"Scheduled");
        std::size_t checkpoint=0;
        constexpr double checkpoints[]={180,300,600};
        while (!interrupted && !state.routeChanged.load()) {
            const auto played=state.content.load(std::memory_order_acquire);
            const auto snapshot=pipeline.snapshot();
            if (active<changeCount) {
                if (snapshot.generation!=requestGenerations[active])
                    throw std::runtime_error("Speed request generation changed unexpectedly");
                if (snapshot.state==ts::prototype::Phase39RequestState::Rejected ||
                    snapshot.state==ts::prototype::Phase39RequestState::Cancelled) {
                    requestStates[active]=snapshot.state==ts::prototype::Phase39RequestState::Rejected
                        ? "Rejected" : "Cancelled";
                    if (snapshot.state==ts::prototype::Phase39RequestState::Rejected)
                        ++rejected;
                    else ++cancelled;
                    active=changeCount;
                    if (!continueRejected || cancelled) strictFailure=true;
                } else if (snapshot.state==ts::prototype::Phase39RequestState::Applied) {
                    if (requestStates[active]=="Requested") requestStates[active]="Applied";
                    if (state.completionPresentationGeneration.load(
                            std::memory_order_acquire)==requestGenerations[active]) {
                        const auto completion=state.completionPresentationNs.load();
                        const auto apply=state.appliedPresentationGeneration.load()==
                            requestGenerations[active] ?
                            state.appliedPresentationNs.load() : 0;
                        applyLatencyMs[active]=apply && apply>=requestMachNs[active] ?
                            (apply-requestMachNs[active])/1e6 : -1;
                        completionLatencyMs[active]=completion>=requestMachNs[active] ?
                            (completion-requestMachNs[active])/1e6 : -1;
                        requestStates[active]="Completed";
                        ++observed;
                        active=changeCount;
                    }
                }
            }
            if (strictFailure) break;
            if (active==changeCount && sent<changeCount &&
                played>=schedule[sent].outputFrame) {
                const auto ticks=mach_absolute_time();
                const auto requestNs=static_cast<std::uint64_t>(
                    (static_cast<long double>(ticks)*state.numer)/state.denom);
                const auto result=forceRejectFirst && sent==0 ?
                    ts::prototype::Phase39RequestResult::Invalid :
                    pipeline.requestSpeed(schedule[sent].speed,played);
                if (result==ts::prototype::Phase39RequestResult::Accepted) {
                    requestMachNs[sent]=requestNs;
                    requestGenerations[sent]=pipeline.snapshot().generation;
                    requestStates[sent]="Requested";
                    active=sent++;
                } else if (result==ts::prototype::Phase39RequestResult::Busy) {
                    requestStates[sent]="Busy";
                } else if (result!=ts::prototype::Phase39RequestResult::Busy) {
                    requestStates[sent]=result==ts::prototype::Phase39RequestResult::Duplicate ?
                        "Duplicate" : result==ts::prototype::Phase39RequestResult::Stopped ?
                        "Stopped" : "Rejected";
                    ++rejected;
                    ++sent;
                    if (!continueRejected) strictFailure=true;
                }
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
        if (active<changeCount && requestStates[active]!="Completed") {
            requestStates[active]="Cancelled";
            ++cancelled;
        }
        for (std::size_t i=sent;i<changeCount;++i)
            requestStates[i]="Stopped";
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
                 <<"profile=Phase43-safe-density-research\n"
                 <<"requested_changes="<<changeCount<<'\n'
                 <<"sent_changes="<<sent<<'\n'
                 <<"observed_completions="<<observed<<'\n'
                 <<"rejected_changes="<<rejected<<'\n'
                 <<"cancelled_changes="<<cancelled<<'\n'
                 <<"reject_policy="<<(continueRejected ? "Continue" : "Strict")<<'\n'
                 <<"fifo_capacity_frames="<<fifoFrames<<'\n'
                 <<"lead_limit_frames="<<leadLimit<<'\n'
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
                 <<"presented_audio_timeline_frames="
                 <<state.presentationFrames.load()<<'\n'
                 <<"output_length="<<status.outputLength<<'\n'
                 <<"eos_drained="<<endDrained<<'\n'
                 <<"route_changed="<<state.routeChanged.load()<<'\n'
                 <<"interrupted="<<interrupted<<'\n'
                 <<"fifo_high_water="<<status.fifoHighWater<<'\n'
                 <<"fifo_rejected_writes="<<status.rejectedWrites<<'\n'
                 <<"underrun_frames="<<status.underrunFrames<<'\n'
                 <<"max_worker_chunk_ms="<<status.maxWorkerChunkSeconds*1000<<'\n'
                 <<"max_worker_cycle_ms="<<status.maxWorkerCycleSeconds*1000<<'\n'
                 <<"p95_worker_cycle_ms="<<pipeline.workerCycleP95Seconds()*1000<<'\n'
                 <<"p99_worker_cycle_ms="<<pipeline.workerCycleP99Seconds()*1000<<'\n'
                 <<"p95_worker_chunk_ms="<<pipeline.workerChunkP95Seconds()*1000<<'\n'
                 <<"max_callback_ms="<<state.maxCallbackNs.load()/1e6<<'\n'
                 <<"callback_deadline_misses="<<state.deadlineMisses.load()<<'\n'
                 <<"callback_format_errors="<<state.formatErrors.load()<<'\n'
                 <<"callback_cpp_allocations="<<renderCppAllocations.load()<<'\n'
                 <<"peak_rss_mib="<<usage.ru_maxrss/1048576.0<<'\n'
                 <<"last_applied_callback_generation="
                 <<state.appliedPresentationGeneration.load()<<'\n'
                 <<"last_completion_callback_generation="
                 <<state.completionPresentationGeneration.load()<<'\n'
                 <<"control_accept_ms="
                 <<(status.acceptedNs>=status.requestNs
                    ? (status.acceptedNs-status.requestNs)/1e6 : -1)<<'\n'
                 <<"accept_to_worker_ms="
                 <<(status.workerSeenNs>=status.acceptedNs
                    ? (status.workerSeenNs-status.acceptedNs)/1e6 : -1)<<'\n'
                 <<"worker_to_plan_ms="
                 <<(status.planNs>=status.workerSeenNs
                    ? (status.planNs-status.workerSeenNs)/1e6 : -1)<<'\n'
                 <<"plan_to_applied_callback_ms=per_change_below\n";
        const auto metrics=pipeline.planMetrics();
        const auto latencySummary=[](std::vector<double> values) {
            values.erase(std::remove_if(values.begin(),values.end(),
                [](double value){ return value<0; }),values.end());
            if (values.empty()) return std::array<double,3>{-1,-1,-1};
            std::sort(values.begin(),values.end());
            const auto at=[&](double quantile) {
                return values[static_cast<std::size_t>(std::ceil(
                    quantile*values.size()))-1];
            };
            return std::array<double,3>{at(0.5),at(0.95),values.back()};
        };
        const auto latency=latencySummary(applyLatencyMs);
        std::cout<<"apply_latency_median_ms="<<latency[0]<<'\n'
                 <<"apply_latency_p95_ms="<<latency[1]<<'\n'
                 <<"apply_latency_max_ms="<<latency[2]<<'\n';
        for (std::size_t i=0;i<metrics.size();++i) {
            const auto position=std::find(requestGenerations.begin(),
                requestGenerations.end(),metrics[i].generation);
            const auto requestIndex=position==requestGenerations.end() ?
                changeCount : static_cast<std::size_t>(position-requestGenerations.begin());
            std::cout<<"change="<<i+1
                     <<" generation="<<metrics[i].generation
                     <<" from="<<metrics[i].from.value()
                     <<" target="<<metrics[i].target.value()
                     <<" applied_output="<<metrics[i].plan.appliedOutputSample
                     <<" completed_output="<<metrics[i].plan.completionOutputSample
                     <<" low_next_input="<<metrics[i].firstUnprocessedResolutionInputs[0]
                     <<" mid_next_input="<<metrics[i].firstUnprocessedResolutionInputs[1]
                     <<" high_next_input="<<metrics[i].firstUnprocessedResolutionInputs[2]
                     <<" lp250_next_source="<<metrics[i].firstUnprocessedFirSources[0]
                     <<" lp3500_next_source="<<metrics[i].firstUnprocessedFirSources[1]
                     <<" plan_ms="<<metrics[i].planMilliseconds
                     <<" apply_callback_ms="<<(requestIndex<applyLatencyMs.size() ?
                        applyLatencyMs[requestIndex] : -1)
                     <<" complete_callback_ms="
                     <<(requestIndex<completionLatencyMs.size() ?
                        completionLatencyMs[requestIndex] : -1)<<'\n';
        }
        for (std::size_t i=0;i<changeCount;++i)
            std::cout<<"request_result="<<i+1<<" state="<<requestStates[i]
                     <<" generation="<<requestGenerations[i]
                     <<" scheduled_frame="<<schedule[i].outputFrame<<'\n';
        return strictFailure || cancelled || sent!=changeCount ||
            (!continueRejected && observed!=changeCount) ||
            (maxSeconds==0 && !endDrained) ||
            (changeCount && !continueRejected &&
             status.state!=ts::prototype::Phase39RequestState::Applied) ||
            status.underrunFrames || status.rejectedWrites || state.deadlineMisses ||
            state.formatErrors || renderCppAllocations.load() || state.routeChanged ||
            (endDrained && state.presentationFrames.load()!=status.outputLength) ? 4 : 0;
    } catch (const std::exception& exception) {
        std::cerr<<"Phase 43: "<<exception.what()<<'\n';
        return 1;
    }
}
