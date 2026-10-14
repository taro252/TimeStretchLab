#ifdef PHASE51_RESEARCH
#include "prototype/Phase51CommandControl.h"
#endif
#import <AVFoundation/AVFoundation.h>
#include <CoreAudio/CoreAudio.h>
#include "prototype/Phase39PlaybackPipeline.h"
#include "prototype/Phase46HostClock.h"
#include "prototype/Phase46Statistics.h"
#include "prototype/Phase47EvidenceFile.h"
#include <iomanip>
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
#include <memory>
#include <pthread.h>

namespace {
thread_local bool insideRender=false;
thread_local std::uint64_t renderThreadId=0,outsideRenderNewCalls=0;
std::atomic<std::uint64_t> renderCppAllocations{0};
void* countedNew(std::size_t bytes,std::size_t alignment=alignof(std::max_align_t)) {
    if (insideRender) renderCppAllocations.fetch_add(1,std::memory_order_relaxed);
    else ++outsideRenderNewCalls;
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
    std::atomic<bool> active{false};
    std::shared_ptr<std::atomic<bool>> routeChanged=std::make_shared<std::atomic<bool>>(false);
    std::atomic<std::uint32_t> activeCallbacks{0};
    std::atomic<std::uint64_t> content{0},presentationFrames{0},calls{0},silence{0};
    std::atomic<std::uint64_t> maxCallbackNs{0},deadlineMisses{0},formatErrors{0};
    std::atomic<std::uint64_t> tailMaxNs{0},tailDeadlineMisses{0},maxTelemetryNs{0};
    std::atomic<std::uint64_t> appliedPresentationNs{0},completionPresentationNs{0};
    std::atomic<std::uint64_t> appliedPresentationGeneration{0},
        completionPresentationGeneration{0};
    struct Event { std::uint64_t before=0,count=0,startNs=0,endNs=0,hostNs=0,renderFrames=0,
        available=0,lastPublicationUnixNs=0,threadId=0,wanted=0;
        std::uint64_t sequence=0,epoch=0,generation=0,lastPublicationMachNs=0,ioCompleteNs=0,earlyEndNs=0;
        std::uint32_t timestampFlags=0;
        double sampleTime=0;
        ts::prototype::Phase46HostClock::Evidence evidence{}; };
    std::vector<Event> events; // Allocated before starting the audio engine.
    std::uint64_t bridgeMachNs=0,bridgeUnixNs=0;
    std::atomic<std::uint64_t> eventIndex{0};
    std::atomic<std::uint64_t> hostValidCalls{0},hostMissingCalls{0};
    ts::prototype::Phase46HostClock hostClock; // Serial source callback, read after quiescence.
    std::uint64_t epoch=1,hostBackward=0,hostCadenceErrors=0,sampleErrors=0,halWindowMisses=0,hostOffsetOutliers=0;
    double sourcePresentationLatencyMs=0;
    std::int64_t minStartMinusHost=INT64_MAX,maxStartMinusHost=INT64_MIN;
    std::uint64_t maxHostProgressError=0;
};
struct PlaybackGuard {
    AVAudioEngine* engine;
    State* state;
    ts::prototype::Phase39PlaybackPipeline* pipeline;
    id observer;
    AVAudioSourceNode* source;
    bool cleaned=false;
    void quiesceAudio() noexcept {
        state->active.store(false,std::memory_order_release);
        if (observer) [[NSNotificationCenter defaultCenter] removeObserver:observer];
        observer=nil;
        if (engine.isRunning) [engine stop];
        while (state->activeCallbacks.load(std::memory_order_acquire))
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        if (source) { [engine detachNode:source]; source=nil; }
    }
    void stop() noexcept {
        if (cleaned) return;
        cleaned=true;
        quiesceAudio();
        pipeline->stop();
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
OSStatus render(State* state,BOOL* isSilence,const AudioTimeStamp* timestamp,AVAudioFrameCount frames,
                AudioBufferList* buffers) noexcept {
    insideRender=true;
    state->activeCallbacks.fetch_add(1,std::memory_order_acq_rel);
    const auto start=mach_absolute_time();
    State::Event* recordedEvent=nullptr;
    if (!renderThreadId) pthread_threadid_np(nullptr,&renderThreadId);
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
        const auto available=state->pipeline->available();
        const auto lastPublication=state->pipeline->lastPublishedUnixNs();
        const auto received=state->pipeline->pullAudio(channel,wanted);
        for (std::uint32_t c=0;c<state->channels;++c)
            std::memset(channel[c]+wanted,0,(frames-wanted)*sizeof(float));
        const auto ioDone=mach_absolute_time();
        state->content.store(before+received,std::memory_order_release);
        state->presentationFrames.fetch_add(wanted,std::memory_order_relaxed);
        state->silence.fetch_add(wanted-received,std::memory_order_relaxed);
        state->calls.fetch_add(1,std::memory_order_relaxed);
        const auto now=mach_absolute_time();
        const auto ns=static_cast<std::uint64_t>(
            (static_cast<long double>(now)*state->numer)/state->denom);
        std::uint64_t hostNs=0;
        const bool hostValid=timestamp && (timestamp->mFlags & kAudioTimeStampHostTimeValid);
        const bool sampleValid=timestamp && (timestamp->mFlags & kAudioTimeStampSampleTimeValid);
        if (hostValid) {
            state->hostValidCalls.fetch_add(1,std::memory_order_relaxed);
            hostNs=static_cast<std::uint64_t>((static_cast<long double>(timestamp->mHostTime)*
                state->numer)/state->denom);
        } else state->hostMissingCalls.fetch_add(1,std::memory_order_relaxed);
        const auto startNs=static_cast<std::uint64_t>((static_cast<long double>(start)*state->numer)/state->denom);
        const auto evidence=state->hostClock.observe(state->epoch,startNs,ns,hostValid,hostNs,
            sampleValid,sampleValid ? timestamp->mSampleTime : 0,frames,state->rate);
        state->hostBackward+=evidence.hostBackwards;
        state->hostCadenceErrors+=evidence.cadenceError;
        state->sampleErrors+=evidence.sampleError;
        state->halWindowMisses+=evidence.halWindowMiss;
        state->hostOffsetOutliers+=evidence.offsetOutlier;
        if (hostValid) {
            state->minStartMinusHost=std::min(state->minStartMinusHost,evidence.startMinusHostNs);
            state->maxStartMinusHost=std::max(state->maxStartMinusHost,evidence.startMinusHostNs);
            state->maxHostProgressError=std::max(state->maxHostProgressError,
                static_cast<std::uint64_t>(std::abs(evidence.hostProgressErrorNs)));
        }
        if (!state->events.empty()) {
            const auto index=state->eventIndex.fetch_add(1,std::memory_order_relaxed);
            auto& event=state->events[index%state->events.size()];
            recordedEvent=&event;
            event={before,received,startNs,ns,hostNs,frames,
                available,lastPublication,renderThreadId,wanted};
            event.ioCompleteNs=static_cast<std::uint64_t>((static_cast<long double>(ioDone)*state->numer)/state->denom);
            event.sequence=index+1;event.epoch=state->epoch;event.generation=markers.generation;
            event.lastPublicationMachNs=state->pipeline->lastPublishedMachNs();
            event.timestampFlags=timestamp ? timestamp->mFlags : 0;
            event.sampleTime=sampleValid ? timestamp->mSampleTime : 0;
            event.evidence=evidence;
        }
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
    if (recordedEvent) {
        recordedEvent->endNs=static_cast<std::uint64_t>((static_cast<long double>(start+ticks)*
            state->numer)/state->denom);
        const bool missed=recordedEvent->hostNs && static_cast<long double>(recordedEvent->endNs)>
            recordedEvent->hostNs+std::max(100000.0,2e9/state->rate);
        if (missed && !recordedEvent->evidence.halWindowMiss) ++state->halWindowMisses;
        recordedEvent->evidence.halWindowMiss=missed;
    }
    auto old=state->maxCallbackNs.load(std::memory_order_relaxed);
    while (old<ns && !state->maxCallbackNs.compare_exchange_weak(old,ns,std::memory_order_relaxed)) {}
    if (ns>static_cast<std::uint64_t>(std::llround(frames*1e9/state->rate)))
        state->deadlineMisses.fetch_add(1,std::memory_order_relaxed);
    // Tail includes the existing timestamp bookkeeping and atomic updates.
    // Only its own final stores and the quiescence decrement remain after it.
    const auto tail=mach_absolute_time();
    const auto tailNs=static_cast<std::uint64_t>((static_cast<long double>(tail)*state->numer)/state->denom);
    const auto totalNs=static_cast<std::uint64_t>((static_cast<long double>(tail-start)*state->numer)/state->denom);
    if (recordedEvent) {
        recordedEvent->earlyEndNs=recordedEvent->endNs;recordedEvent->endNs=tailNs;
        const bool tailHalMiss=recordedEvent->hostNs && tailNs>
            recordedEvent->hostNs+std::max(100000.0,2e9/state->rate);
        if (tailHalMiss && !recordedEvent->evidence.halWindowMiss) ++state->halWindowMisses;
        recordedEvent->evidence.halWindowMiss=tailHalMiss;
        const auto overhead=tailNs-recordedEvent->ioCompleteNs;
        auto prior=state->maxTelemetryNs.load(std::memory_order_relaxed);
        while (prior<overhead && !state->maxTelemetryNs.compare_exchange_weak(prior,overhead,std::memory_order_relaxed)) {}
    }
    auto tailOld=state->tailMaxNs.load(std::memory_order_relaxed);
    while (tailOld<totalNs && !state->tailMaxNs.compare_exchange_weak(tailOld,totalNs,std::memory_order_relaxed)) {}
    if (totalNs>static_cast<std::uint64_t>(std::llround(frames*1e9/state->rate)))
        state->tailDeadlineMisses.fetch_add(1,std::memory_order_relaxed);
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
        const auto configured=[](const char* key,std::size_t fallback) {
            return std::getenv(key) ? static_cast<std::size_t>(std::stoull(std::getenv(key))) : fallback;
        };
        const std::size_t fifoFrames=configured("PHASE46_FIFO",16384),
            blockFrames=configured("PHASE46_DSP_BLOCK",2048),leadLimit=configured("PHASE46_LEAD",12288);
        const auto prepareBegin=Clock::now();
        const bool profileEnabled=std::getenv("PHASE43_PROFILE") || std::getenv("PHASE45_LIVE_WORKERS");
        ts::prototype::Phase39PlaybackPipeline pipeline(
            argv[1],initial,fifoFrames,blockFrames,leadLimit,
#ifdef PHASE51_RESEARCH
            std::getenv("PHASE51_L2") ? ts::prototype::Phase39Planning::L2 : ts::prototype::Phase39Planning::C,
#else
            ts::prototype::Phase39Planning::C,
#endif
            ts::prototype::Phase39DensityDiagnostic::SafeGuarded,
            profileEnabled,{},0,0,profileEnabled ?
                std::function<std::uint64_t()>([] { return outsideRenderNewCalls; }) :
                std::function<std::uint64_t()>{}
#ifdef PHASE50_RESEARCH
                ,std::getenv("PHASE50_PRECISE_BOUNDARY")!=nullptr
#endif
                );
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
        state.bridgeMachNs=static_cast<std::uint64_t>((static_cast<long double>(mach_absolute_time())*
            state.numer)/state.denom);
        state.bridgeUnixNs=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
        if (std::getenv("PHASE45_LIVE_EVENTS")) state.events.resize(65536);
        AVAudioEngine* engine=nil;
        AVAudioFormat* hardware=nil;
        AVAudioFormat* format=nil;
        AVAudioSourceNode* source=nil;
        id observer=nil;
        State* pointer=&state;
        const auto routeFlag=state.routeChanged;
        AudioDeviceID device=0;
        const auto configureAudio=[&] {
        @try {
            engine=[[AVAudioEngine alloc] init];
            UInt32 bytes=sizeof(device);
            AudioObjectPropertyAddress address{kAudioHardwarePropertyDefaultOutputDevice,
                kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
            if (AudioObjectGetPropertyData(kAudioObjectSystemObject,&address,0,nullptr,&bytes,&device)!=noErr)
                throw std::runtime_error("Cannot acquire default output device identity");
            hardware=[engine.outputNode outputFormatForBus:0];
            if (hardware.sampleRate<=0 || hardware.channelCount==0)
                throw std::runtime_error("No audio output device");
            format=[[AVAudioFormat alloc]
                initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:pipeline.sampleRate()
                channels:static_cast<AVAudioChannelCount>(pipeline.channels()) interleaved:NO];
            source=[[AVAudioSourceNode alloc] initWithFormat:format
                renderBlock:^OSStatus(BOOL* silent,const AudioTimeStamp* timestamp,
                                      AVAudioFrameCount frames,AudioBufferList* data) {
                    return render(pointer,silent,timestamp,frames,data);
                }];
            [engine attachNode:source];
            [engine connect:source to:engine.mainMixerNode format:format];
            engine.mainMixerNode.outputVolume=std::getenv("PHASE43_SILENT") ? 0.0f : 0.5f;
            // The playback gain is never applied to the raw DSP FIFO.
            [engine prepare];
            observer=[[NSNotificationCenter defaultCenter]
                addObserverForName:AVAudioEngineConfigurationChangeNotification object:engine
                queue:nil usingBlock:^(NSNotification*) {
                    routeFlag->store(true,std::memory_order_release);
                }];
        } @catch (NSException* exception) {
            throw std::runtime_error([[exception description] UTF8String]);
        }
        };
        configureAudio();
        PlaybackGuard guard{engine,&state,&pipeline,observer,source};
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
        state.sourcePresentationLatencyMs=source.outputPresentationLatency*1000;
        CpuStress stress(std::getenv("PHASE43_STRESS")!=nullptr);
        const auto playStart=Clock::now();
        const double injectRouteAt=std::getenv("PHASE45_ROUTE_AFTER_SECONDS") ?
            std::stod(std::getenv("PHASE45_ROUTE_AFTER_SECONDS")) : -1;
        bool injectedRoute=false;
        std::size_t routeChanges=0,resumes=0;
        std::uint64_t savedOutput=0;
        double savedTarget=initial.value();
        const bool continueRejected=std::getenv("PHASE43_REJECT_POLICY") &&
            std::strcmp(std::getenv("PHASE43_REJECT_POLICY"),"continue")==0;
        const bool forceRejectFirst=std::getenv("PHASE44_FORCE_REJECT_FIRST")!=nullptr;
        std::size_t sent=0,observed=0,rejected=0,cancelled=0,active=changeCount;
        bool strictFailure=false;
        std::vector<double> applyLatencyMs(changeCount,-1),completionLatencyMs(changeCount,-1);
        std::vector<std::uint64_t> requestMachNs(changeCount,0),
            requestGenerations(changeCount,0);
        std::vector<std::string> requestStates(changeCount,"Scheduled");
#ifdef PHASE51_RESEARCH
        using Commands=ts::prototype::Phase51CommandControl;
        const std::string policyName=std::getenv("PHASE51_POLICY") ? std::getenv("PHASE51_POLICY") : "defer";
        const auto policy=policyName=="latest" ? Commands::Policy::Latest : policyName=="strict" ? Commands::Policy::Strict :
            policyName=="continue" ? Commands::Policy::Continue : policyName=="defer" ? Commands::Policy::Defer :
            throw std::invalid_argument("Unknown research control policy");
        Commands commands(changeCount,policy);
        const auto machNow=[&](){return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*state.numer/state.denom);};
        const auto anchorMach=machNow();
        const auto anchorSteady=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
        const auto clockOffset=static_cast<std::int64_t>(anchorMach)-anchorSteady;
        const auto bridgeClockErrorNs=machNow()-anchorMach;
        for(std::size_t i=0;i<changeCount;++i) commands.operations[i].scheduled=anchorMach+
            static_cast<std::uint64_t>(schedule[i].outputFrame*1e9/state.rate);
        std::size_t arrivals=0,acceptedOperations=0;
        const bool wallSchedule=std::getenv("PHASE51_WALL_SCHEDULE")!=nullptr;
#endif
        std::size_t checkpoint=0;
        constexpr double checkpoints[]={180,300,600};
        while (!interrupted) {
            if (!injectedRoute && injectRouteAt>=0 &&
                Clock::now()-playStart>=std::chrono::duration<double>(injectRouteAt)) {
                state.routeChanged->store(true,std::memory_order_release);injectedRoute=true;
            }
            if (state.routeChanged->load(std::memory_order_acquire)) {
                ++routeChanges;
                guard.quiesceAudio(); // Audio fully quiescent before any buffer/engine release.
                savedOutput=state.content.load(std::memory_order_acquire);
                savedTarget=pipeline.snapshot().target.value();
                std::cout<<"route_pause_output="<<savedOutput<<" target="<<savedTarget<<std::endl;
                if (!std::getenv("PHASE45_ROUTE_RESUME") &&
                    !std::getenv("PHASE45_ROUTE_AUTO_RESUME_TEST")) break;
                if (!std::getenv("PHASE45_ROUTE_AUTO_RESUME_TEST")) {
                    std::cout<<"新しい出力装置で再開するにはEnter、終了するにはqを入力してください。"<<std::endl;
                    std::string answer;std::getline(std::cin,answer);
                    if (!std::cin || answer=="q") break;
                }
                // DSP, TimeMap and unread FIFO remain owned by the same worker.
                configureAudio();
                guard.engine=engine;guard.source=source;guard.observer=observer;
                state.routeChanged->store(false,std::memory_order_release);
                NSError* resumeError=nil;
                ++state.epoch;
                state.active.store(true,std::memory_order_release);
                if (![engine startAndReturnError:&resumeError]) {
                    state.active.store(false,std::memory_order_release);
                    throw std::runtime_error("Audio restart failed");
                }
                ++resumes;
                state.sourcePresentationLatencyMs=source.outputPresentationLatency*1000;
            }
            const auto played=state.content.load(std::memory_order_acquire);
            const auto snapshot=pipeline.snapshot();
#ifdef PHASE51_RESEARCH
            const auto controlNow=machNow();
            if(active<changeCount){
                auto& op=commands.operations[active];
                if(snapshot.generation!=op.generation)throw std::runtime_error("Control generation mismatch");
                if(snapshot.workerSeenNs)op.workerSeen=static_cast<std::uint64_t>(static_cast<std::int64_t>(snapshot.workerSeenNs)+clockOffset);
                if(snapshot.state==ts::prototype::Phase39RequestState::Rejected || snapshot.state==ts::prototype::Phase39RequestState::Cancelled){
                    op.state=snapshot.state==ts::prototype::Phase39RequestState::Rejected ? "Rejected" : "Cancelled";
                    if(op.state=="Rejected")++rejected;else ++cancelled;
                    requestStates[active]=op.state;active=changeCount;
                    if(policy==Commands::Policy::Strict)strictFailure=true;
                }else if(snapshot.state==ts::prototype::Phase39RequestState::Applied){
                    op.state="Applied";requestStates[active]="Applied";
                    if(pipeline.researchTransitionComplete() && state.completionPresentationGeneration.load()==op.generation){
                        op.ready=pipeline.researchCommandReady() ? controlNow : 0;op.state="Completed";requestStates[active]="Completed";
                        const auto apply=state.appliedPresentationGeneration.load()==op.generation ? state.appliedPresentationNs.load() : 0;
                        applyLatencyMs[active]=apply>=op.sent ? (apply-op.sent)/1e6 : -1;
                        completionLatencyMs[active]=(state.completionPresentationNs.load()-op.sent)/1e6;
                        ++observed;active=changeCount;
                    }
                }
            }
            bool ready=active==changeCount && pipeline.researchCommandReady();
            while(arrivals<changeCount && (wallSchedule ? controlNow>=commands.operations[arrivals].scheduled : played>=schedule[arrivals].outputFrame)){
                commands.arrive(arrivals,controlNow,!ready);
                requestStates[arrivals]=commands.operations[arrivals].state;++arrivals;
            }
            if(commands.failed)strictFailure=true;
            const auto index=commands.next(ready,controlNow);
            if(!strictFailure && index!=Commands::none){
                const auto send=machNow();const auto result=forceRejectFirst && index==0 ? ts::prototype::Phase39RequestResult::Invalid : pipeline.requestSpeed(schedule[index].speed,played);
                if(result==ts::prototype::Phase39RequestResult::Accepted){
                    commands.dispatch(index,send);auto& op=commands.operations[index];op.accepted=machNow();
                    op.generation=pipeline.snapshot().generation;
                    requestMachNs[index]=send;requestGenerations[index]=op.generation;requestStates[index]="Requested";
                    active=index;++acceptedOperations;
                }else if(result==ts::prototype::Phase39RequestResult::Busy){++commands.operations[index].busyPolls;}
                else {commands.dispatch(index,send);commands.operations[index].state=result==ts::prototype::Phase39RequestResult::Duplicate ? "Duplicate":"Rejected";
                    requestStates[index]=commands.operations[index].state;if(commands.operations[index].state=="Rejected"){++rejected;if(policy==Commands::Policy::Strict)strictFailure=true;}}
            }
            sent=arrivals;
            if(strictFailure)break;
#else
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
#endif
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
        const bool endDrained=!state.routeChanged->load() && !interrupted && pipeline.drained() &&
            state.content.load(std::memory_order_acquire)>=pipeline.snapshot().outputLength;
        if (endDrained) {
            const auto latency=std::max(0.1,engine.outputNode.presentationLatency+0.1);
            std::this_thread::sleep_for(std::chrono::duration<double>(latency));
        }
        guard.stop();
        pipeline.rethrowWorkerError();
        const auto status=pipeline.snapshot();
        const auto stall=pipeline.stallObservation();
        UInt32 deviceBufferFrames=0,bufferBytes=sizeof(deviceBufferFrames);
        AudioObjectPropertyAddress bufferAddress{kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        const auto bufferQuery=AudioObjectGetPropertyData(device,&bufferAddress,0,nullptr,&bufferBytes,&deviceBufferFrames);
        const bool reportEos=endDrained && !state.routeChanged->load() && !interrupted;
        const bool anyRouteChange=routeChanges!=0 || state.routeChanged->load();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto userCpu=usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6;
        const auto systemCpu=usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6;
        const auto wall=std::chrono::duration<double>(Clock::now()-playStart).count();
        const auto deviceLatencyMs=engine.outputNode.presentationLatency*1000;
        std::cout<<std::setprecision(17)<<"initial_speed="<<initialName<<'\n'
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
                 <<"worker_qos_requested="<<(std::getenv("PHASE44_WORKER_QOS") ? "user_initiated" : "inherited")<<'\n'
                 <<"worker_qos_applied="<<status.workerQosApplied<<'\n'
                 <<"cpu_stress_threads="<<(std::getenv("PHASE43_STRESS") ? 2 : 0)<<'\n'
                 <<"cpu_stress_ticks="<<stress.ticks.load()<<'\n'
                 <<"prefill_seconds="<<prefill<<'\n'
                 <<"analysis_seconds="<<analysisSeconds<<'\n'
                 <<"output_device_rate="<<hardware.sampleRate<<'\n'
                 <<"output_device_buffer_frames="<<(bufferQuery==noErr ? deviceBufferFrames : 0)<<'\n'
                 <<"output_device_buffer_query_ok="<<(bufferQuery==noErr)<<'\n'
                 <<"output_device_id="<<device<<'\n'
                 <<"output_device_channels="<<hardware.channelCount<<'\n'
                 <<"dsp_sample_rate="<<pipeline.sampleRate()<<'\n'
                 <<"dsp_channels="<<pipeline.channels()<<'\n'
                 <<"input_frames="<<pipeline.inputFrames()<<'\n'
                 <<"format_acquired=1\ndevice_acquired=1\nworker_errors=0\n"
                 <<"callback_allocation_counter_enabled=1\n"
                 <<"clock_bridge_mach_ns="<<state.bridgeMachNs<<'\n'
                 <<"clock_bridge_unix_ns="<<state.bridgeUnixNs<<'\n'
                 <<"stop_reason="<<(anyRouteChange && !reportEos ? "RouteChanged" :
                       interrupted ? "Interrupted" : reportEos ? "EOS" :
                       strictFailure ? "Rejected" : "DurationLimit")<<'\n'
                 <<"wall_seconds="<<wall<<'\n'
                 <<"cpu_user_seconds="<<userCpu<<'\n'
                 <<"cpu_system_seconds="<<systemCpu<<'\n'
                 <<"controlled_stall_configured="<<stall.configured<<'\n'
                 <<"controlled_stall_triggered="<<stall.triggered<<'\n'
                 <<"controlled_stall_cancelled="<<stall.cancelled<<'\n'
                 <<"controlled_stall_requested_ms="<<stall.requestedMs<<'\n'
                 <<"controlled_stall_wall_s="<<stall.wallSeconds<<'\n'
                 <<"controlled_stall_cpu_s="<<stall.cpuSeconds<<'\n'
                 <<"controlled_stall_start_mach_ns="<<stall.startMachNs<<'\n'
                 <<"controlled_stall_measurement_end_mach_ns="<<stall.measurementEndMachNs<<'\n'
                 <<"controlled_stall_end_mach_ns="<<stall.endMachNs<<'\n'
                 <<"controlled_stall_fifo_goal="<<stall.fifoGoal<<'\n'
                 <<"controlled_stall_fifo_before="<<stall.fifoBefore<<'\n'
                 <<"controlled_stall_fifo_after="<<stall.fifoAfter<<'\n'
                 <<"controlled_stall_published_frames="<<stall.publishedFrames<<'\n'
                 <<"controlled_stall_cycle="<<stall.cycleSequence<<'\n'
                 <<"controlled_stall_input_low="<<stall.nextInput[0]<<'\n'
                 <<"controlled_stall_input_mid="<<stall.nextInput[1]<<'\n'
                 <<"controlled_stall_input_high="<<stall.nextInput[2]<<'\n'
                 <<"controlled_stall_worker_tid="<<stall.threadId<<'\n'
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
                 <<"eos_drained="<<reportEos<<'\n'
                 <<"route_changed="<<anyRouteChange<<'\n'
                 <<"route_change_count="<<routeChanges<<"\nroute_resume_count="<<resumes<<'\n'
                 <<"saved_output_frame="<<savedOutput<<"\nsaved_target_speed="<<savedTarget<<'\n'
                 <<"active_callbacks_after_stop="<<state.activeCallbacks.load()<<'\n'
                 <<"worker_stopped="<<pipeline.finished()<<'\n'
                 <<"interrupted="<<interrupted<<'\n'
                 <<"fifo_high_water="<<status.fifoHighWater<<'\n'
                 <<"fifo_rejected_writes="<<status.rejectedWrites<<'\n'
                 <<"underrun_frames="<<status.underrunFrames<<'\n'
                 <<"max_worker_chunk_ms="<<status.maxWorkerChunkSeconds*1000<<'\n'
                 <<"max_worker_cycle_ms="<<status.maxWorkerCycleSeconds*1000<<'\n'
                 <<"p95_worker_cycle_ms="<<pipeline.workerCycleP95Seconds()*1000<<'\n'
                 <<"p99_worker_cycle_ms="<<pipeline.workerCycleP99Seconds()*1000<<'\n'
                 <<"p95_worker_chunk_ms="<<pipeline.workerChunkP95Seconds()*1000<<'\n'
                 <<"max_callback_ms="<<state.tailMaxNs.load()/1e6
                 <<"\nmax_callback_early_ms="<<state.maxCallbackNs.load()/1e6
                 <<"\nmax_callback_telemetry_ms="<<state.maxTelemetryNs.load()/1e6<<'\n'
                 <<"callback_deadline_misses="<<state.tailDeadlineMisses.load()<<'\n'
                 <<"callback_format_errors="<<state.formatErrors.load()<<'\n'
                 <<"max_callback_host_late_ms="<<std::max<std::int64_t>(0,state.maxStartMinusHost)/1e6<<'\n'
                 <<"host_timestamp_valid_callbacks="<<state.hostValidCalls.load()<<'\n'
                 <<"host_timestamp_missing_callbacks="<<state.hostMissingCalls.load()<<'\n'
                 <<"host_timestamp_backwards="<<state.hostBackward<<'\n'
                 <<"host_timestamp_cadence_errors="<<state.hostCadenceErrors<<'\n'
                 <<"host_timestamp_offset_outliers="<<state.hostOffsetOutliers<<'\n'
                 <<"sample_timestamp_errors="<<state.sampleErrors<<'\n'
                 <<"hal_window_deadline_misses="<<state.halWindowMisses<<'\n'
                 <<"hal_ready_deadline_definition=host_first_frame_plus_tolerance\n"
                 <<"host_continuity_tolerance_ns="<<std::max(100000.0,2e9/state.rate)<<'\n'
                 <<"min_callback_start_minus_host_ns="<<state.minStartMinusHost<<'\n'
                 <<"max_callback_start_minus_host_ns="<<state.maxStartMinusHost<<'\n'
                 <<"max_host_progress_error_ns="<<state.maxHostProgressError<<'\n'
                 <<"source_output_presentation_latency_ms="<<state.sourcePresentationLatencyMs<<'\n'
                 <<"sample_rate_conversion="<<(state.rate!=hardware.sampleRate)<<'\n'
                 <<"worker_pcm_sha256="<<pipeline.workerPcmSha()<<'\n'
                 <<"worker_pcm_hash_enabled="<<pipeline.workerPcmHashEnabled()<<'\n'
                 <<"worker_profile_records_dropped="<<pipeline.profileRecordsDropped()<<'\n'
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
        bool csvSaveFailed=false;
        const auto callbackCount=state.eventIndex.load();
        const auto callbackRetained=std::min<std::uint64_t>(callbackCount,state.events.size());
        const auto workerRecords=pipeline.allBlockProfiles();
        const auto guardRecords=pipeline.guardMetrics();
        std::cout<<"callback_records_total="<<callbackCount
                 <<"\ncallback_records_retained="<<callbackRetained
                 <<"\ncallback_records_evicted="<<callbackCount-callbackRetained
                 <<"\nworker_records_retained="<<workerRecords.size()
                 <<"\nworker_records_total="<<workerRecords.size()+pipeline.profileRecordsDropped()
                 <<"\nreplay_records_expected="<<metrics.size()
                 <<"\nguard_records_expected="<<guardRecords.size()<<'\n';
        try {
        if (const auto path=std::getenv("PHASE45_LIVE_EVENTS")) {
            ts::prototype::Phase47EvidenceFile eventsFile(path);
            auto& events=eventsFile.stream();
            events<<std::setprecision(17);
            events<<"pcm_before,received,callback_start_mach_ns,callback_end_mach_ns,host_mach_ns,render_requested_frames,available_before,last_publication_unix_ns,thread_id,callback_start_unix_ns,wanted,sequence,epoch,generation,last_publication_mach_ns,timestamp_flags,sample_time,start_minus_host_ns,host_delta_ns,host_progress_error_ns,sample_delta,sample_progress_error,host_missing,host_backwards,cadence_error,sample_error,hal_window_miss,io_complete_mach_ns,early_end_mach_ns\n";
            const auto count=state.eventIndex.load();
            const auto retained=std::min<std::uint64_t>(count,state.events.size());
            for (std::uint64_t i=0;i<retained;++i) {
                const auto& e=state.events[(count-retained+i)%state.events.size()];
                events<<e.before<<','<<e.count<<','<<e.startNs<<','<<e.endNs<<','<<e.hostNs<<','<<e.renderFrames
                      <<','<<e.available<<','<<e.lastPublicationUnixNs<<','<<e.threadId<<','
                      <<state.bridgeUnixNs+(e.startNs-state.bridgeMachNs)<<','<<e.wanted<<','
                      <<e.sequence<<','<<e.epoch<<','<<e.generation<<','<<e.lastPublicationMachNs<<','
                      <<e.timestampFlags<<','<<e.sampleTime<<','<<e.evidence.startMinusHostNs<<','
                      <<e.evidence.hostDeltaNs<<','<<e.evidence.hostProgressErrorNs<<','
                      <<e.evidence.sampleDelta<<','<<e.evidence.sampleProgressError<<','
                      <<e.evidence.hostMissing<<','<<e.evidence.hostBackwards<<','
                      <<e.evidence.cadenceError<<','<<e.evidence.sampleError<<','<<e.evidence.halWindowMiss<<','
                      <<e.ioCompleteNs<<','<<e.earlyEndNs<<'\n';
            }
            eventsFile.commit();
        }
        if (const auto path=std::getenv("PHASE45_LIVE_WORKERS")) {
            ts::prototype::Phase47EvidenceFile csvFile(path);
            auto& csv=csvFile.stream();
            csv<<std::setprecision(17);
            csv<<"output_start,start_unix_ns,end_unix_ns,thread_id,cycle_wall_s,cycle_cpu_s,dsp_wall_s,dsp_cpu_s,fifo_wait_s,fifo_write_s,plan_wall_s,plan_cpu_s,mutex_wait_s,mutex_hold_s,allocation_counter_enabled,cpp_new_calls,wav_wall_s,wav_cpu_s,fft_wall_s,fft_cpu_s,phase_wall_s,phase_cpu_s,ola_wall_s,ola_cpu_s,fir_wall_s,fir_cpu_s,start_mach_ns,published_mach_ns,publication_frames,fifo_before_write,fifo_after_write,publication_interval_s,cycle_sequence,injected_pause_wall_s,injected_pause_cpu_s\n";
            for (const auto& b:workerRecords) {
                csv<<b.outputStart<<','<<b.startUnixNs<<','<<b.endUnixNs<<','<<b.threadId<<','
                   <<b.fullCycleWallSeconds<<','<<b.fullCycleCpuSeconds<<','<<b.chunkWallSeconds<<','
                   <<b.chunkCpuSeconds<<','<<b.fifoWaitSeconds<<','<<b.fifoWriteSeconds<<','
                   <<b.planWallSeconds<<','<<b.planCpuSeconds<<','<<b.mutexWaitSeconds<<','
                   <<b.mutexHoldSeconds<<','<<b.allocationCounterEnabled<<',';
                if (b.allocationCounterEnabled) csv<<b.cppNewCalls;else csv<<"unmeasured";
                for (const auto& stage:b.work.stages) csv<<','<<stage.wallSeconds<<','<<stage.threadCpuSeconds;
                csv<<','<<b.startMachNs<<','<<b.publishedMachNs<<','<<b.publicationFrames<<','
                   <<b.fifoBeforeWrite<<','<<b.fifoAfterWrite<<','<<b.publicationIntervalSeconds<<','<<b.cycleSequence<<','<<b.injectedPauseWallSeconds<<','<<b.injectedPauseCpuSeconds<<'\n';
            }
            csvFile.commit();
            ts::prototype::Phase47EvidenceFile guardsFile(std::string(path)+".guard.csv");
            auto& guards=guardsFile.stream();
            guards<<"generation,fifo_at_plan,safe,candidates,guard_wall_s,guard_cpu_s,weight_error_low,weight_error_mid,weight_error_high\n";
            for (const auto& m:guardRecords) {
                guards<<m.generation<<','<<m.fifoAtPlan<<','<<m.decision.safe<<','
                      <<m.decision.candidatesTried<<','<<m.decision.guardWallSeconds<<','
                      <<m.decision.guardThreadCpuSeconds;
                for (const auto value:m.decision.weightPredictionAbsoluteError) guards<<','<<value;
                guards<<'\n';
            }
            guardsFile.commit();
        }
        if (const auto path=std::getenv("PHASE45_LIVE_PLAN_CSV")) {
            ts::prototype::Phase47EvidenceFile replayFile(path);
            auto& replay=replayFile.stream();
            replay<<"generation,requested_output,requested_input,from,target,fence,prepared,published,applied_frame,applied_output,completion_output,density_input,map_bytes,plan_ms,fifo_at_plan,immutable_low,immutable_mid,immutable_high,density_horizon_low,density_horizon_mid,density_horizon_high,ola_low,ola_mid,ola_high,fir250_fence,fir3500_fence,first_mutable_frame,first_safe_frame,next_event_frame,protection_end_frame,ramp_end_frame,held_frames,safe_frames_used,density_output,defer_event_samples,defer_gap_samples,ramp_event_samples,ramp_gap_samples,phase50_precise_fence,phase50_legacy_fence,phase50_state_preserved,next_low_input,next_mid_input,next_high_input,last_low_input,last_mid_input,last_high_input\n";
            for (const auto& m:metrics) {
                replay<<m.generation<<','<<m.requestedOutput<<','<<m.requestedInput<<','
                      <<m.from.value()<<','<<m.target.value()<<','<<m.planningFence<<','
                      <<m.prepared<<','<<m.published<<','<<m.plan.appliedFrame<<','
                      <<m.plan.appliedOutputSample<<','<<m.plan.completionOutputSample<<','
                      <<m.firstDensityChangedInput<<','<<m.timeMapBytes<<','<<m.planMilliseconds<<','<<m.fifoAtPlan;
                for (auto v:m.immutableNodeOutputs) replay<<','<<v;
                for (auto v:m.densityHorizonOutputs) replay<<','<<v;
                for (auto v:m.finalizedOla) replay<<','<<v;
                replay<<','<<m.firstUnprocessedFirSources[0]+4096<<','<<m.firstUnprocessedFirSources[1]+4096
                      <<','<<m.plan.firstMutableFrame<<','<<m.plan.firstSafeFrame<<','<<m.plan.nextEventFrame<<','<<m.plan.protectionEndFrame
                      <<','<<m.plan.rampEndFrame<<','<<m.plan.heldFrames<<','<<m.plan.safeFramesUsed<<','<<m.densityOutput;
                for (auto v:m.heldOutputSamples) replay<<','<<v;
                replay<<','<<m.phase50PreciseFence<<','<<m.phase50LegacyFence<<','<<m.phase50StatePreserved;
                for (auto v:m.firstUnprocessedResolutionInputs) replay<<','<<v;
                for (auto v:m.lastProcessedResolutionInputs) replay<<','<<v;
                replay<<'\n';
            }
            replayFile.commit();
        }
        } catch (const std::exception& exception) {
            csvSaveFailed=true;
            std::cout<<"diagnostic_csv_error="<<exception.what()<<'\n';
        }
        std::cout<<"diagnostic_csv_save_ok="<<!csvSaveFailed<<'\n';
        const auto latencySummary=ts::prototype::phase46LatencySummary;
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
                     <<" operation_mach_ns="<<(requestIndex<changeCount ? requestMachNs[requestIndex] : 0)
                     <<" worker_request_steady_ns="<<metrics[i].requestNs
                     <<" apply_callback_ms="<<(requestIndex<applyLatencyMs.size() ?
                        applyLatencyMs[requestIndex] : -1)
                     <<" legacy_entry_plus_device_ms="<<(requestIndex<applyLatencyMs.size() &&
                         applyLatencyMs[requestIndex]>=0 ? applyLatencyMs[requestIndex]+deviceLatencyMs : -1)
                     <<" complete_callback_ms="
                     <<(requestIndex<completionLatencyMs.size() ?
                        completionLatencyMs[requestIndex] : -1)<<'\n';
        }
        for (std::size_t i=0;i<changeCount;++i)
            std::cout<<"request_result="<<i+1<<" state="<<requestStates[i]
                     <<" generation="<<requestGenerations[i]
                     <<" scheduled_frame="<<schedule[i].outputFrame<<'\n';
#ifdef PHASE51_RESEARCH
        commands.stop(machNow());
        if(const auto path=std::getenv("PHASE51_OPERATIONS")){
            ts::prototype::Phase47EvidenceFile file(path);auto& csv=file.stream();
            csv<<"operation,target,scheduled_mach_ns,observed_mach_ns,sent_mach_ns,accepted_mach_ns,worker_seen_mach_ns,ready_observed_mach_ns,generation,busy_ns,busy_polls,state,clock_bridge_error_ns\n";
            for(std::size_t i=0;i<changeCount;++i){const auto& op=commands.operations[i];
                csv<<i+1<<','<<schedule[i].speed.value()<<','<<op.scheduled<<','<<op.arrived<<','<<op.sent<<','<<op.accepted<<','<<op.workerSeen<<','<<op.ready<<','<<op.generation<<','<<op.busyNs<<','<<op.busyPolls<<','<<op.state<<','<<bridgeClockErrorNs<<'\n';}
            file.commit();
        }
        std::cout<<"research_control_policy="<<policyName<<"\nresearch_accepted_operations="<<acceptedOperations<<"\nresearch_observed_operations="<<arrivals<<'\n';
#endif
        if (csvSaveFailed) return 5;
#ifdef PHASE51_RESEARCH
        return strictFailure || cancelled || observed!=acceptedOperations ||
            (maxSeconds==0 && !reportEos) || status.underrunFrames || status.rejectedWrites || state.tailDeadlineMisses ||
            state.formatErrors || renderCppAllocations.load() || anyRouteChange || state.hostMissingCalls || state.hostBackward ||
            state.hostCadenceErrors || state.hostOffsetOutliers || state.sampleErrors || state.halWindowMisses ||
            (endDrained && state.presentationFrames.load()!=status.outputLength) ? 4 : 0;
#else
        return strictFailure || cancelled || sent!=changeCount ||
            (!continueRejected && observed!=changeCount) ||
            (maxSeconds==0 && !reportEos) ||
            (changeCount && !continueRejected &&
             status.state!=ts::prototype::Phase39RequestState::Applied) ||
            status.underrunFrames || status.rejectedWrites || state.tailDeadlineMisses ||
            state.formatErrors || renderCppAllocations.load() || anyRouteChange ||
            state.hostMissingCalls || state.hostBackward || state.hostCadenceErrors ||
            state.hostOffsetOutliers ||
            state.sampleErrors || state.halWindowMisses ||
            (endDrained && state.presentationFrames.load()!=status.outputLength) ? 4 : 0;
#endif
    } catch (const std::exception& exception) {
        std::cerr<<"Phase 43: "<<exception.what()<<'\n';
        return 1;
    }
}
