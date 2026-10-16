#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#import <AudioUnit/AudioUnit.h>
#include "prototype/Phase58Diagnostics.h"
#include "prototype/Phase46HostClock.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase58FixAllocationProbe.h"
#ifdef PHASE59_RESEARCH
#include "prototype/Phase59Diagnostics.h"
#include "prototype/Phase59ReplaySupport.h"
#endif
#include "audio/WavStream.h"
#include <mach/mach_time.h>
#include <bit>
#include <fstream>
#include <iostream>
#include <cstring>
#include <sys/resource.h>

// Verification executable only: all C++ allocation entry points are counted.
thread_local bool phase58InCallback=false;
std::atomic<std::uint64_t> phase58Allocations{0};
void* operator new(std::size_t n){ts::prototype::phase58::noteDspAllocation();if(phase58InCallback)++phase58Allocations;if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){ts::prototype::phase58::noteDspAllocation();if(phase58InCallback)++phase58Allocations;void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}
void operator delete(void* p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t)noexcept{std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}
void* operator new(std::size_t n,const std::nothrow_t&)noexcept{try{return ::operator new(n);}catch(...){return nullptr;}}
void* operator new[](std::size_t n,const std::nothrow_t&)noexcept{try{return ::operator new[](n);}catch(...){return nullptr;}}
void* operator new(std::size_t n,std::align_val_t a,const std::nothrow_t&)noexcept{try{return ::operator new(n,a);}catch(...){return nullptr;}}
void* operator new[](std::size_t n,std::align_val_t a,const std::nothrow_t&)noexcept{try{return ::operator new[](n,a);}catch(...){return nullptr;}}
void operator delete(void* p,const std::nothrow_t&)noexcept{std::free(p);}void operator delete[](void* p,const std::nothrow_t&)noexcept{std::free(p);}
void operator delete(void* p,std::align_val_t,const std::nothrow_t&)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t,const std::nothrow_t&)noexcept{std::free(p);}
using namespace ts::prototype;
namespace {
struct Record {std::uint64_t start=0,end=0,host=0,epoch=0;double sample=0;std::uint32_t flags=0,frames=0;phase58::RenderResult raw;};
struct Context {
    phase58::RealtimePipeline* pipeline=nullptr;const float* reference=nullptr;std::size_t referenceFrames=0,channels=0;double rate=0;
    float* capture=nullptr;
#ifdef PHASE59_FIX_STARTUP
    struct RenderEntry {std::uint64_t start=0,host=0;double sample=0;std::uint32_t frames=0,flags=0;bool active=false;};
    std::array<RenderEntry,32> renderEntries{};
    std::atomic<std::uint32_t> renderEntryCalls{0};
    struct OutputNotifyRecord {std::uint64_t start=0,host=0;double sample=0;std::uint32_t frames=0,action=0,flags=0,bus=0;};
    std::array<OutputNotifyRecord,1024> outputRecords{};
    std::atomic<std::uint32_t> outputCalls{0};
    bool captureOutputNotify=false;
#endif
    std::atomic<bool> active{false};std::atomic<unsigned> inRender{0};
    std::uint64_t numer=1,denom=1,epoch=1,calls=0,dropped=0,maximum=0,deadlines=0,formats=0;
    std::uint64_t hostMissing=0,hostBackwards=0,hostCadence=0,sampleErrors=0,sampleValid=0,halMisses=0;
    std::uint64_t mismatches=0,firstMismatch=0,firstPcm=0;std::atomic<std::uint64_t> lastTarget{0};std::uint32_t actualBits=0,expectedBits=0;
    std::vector<Record> records;Phase46HostClock clock;
    std::uint64_t now()const noexcept{return std::uint64_t(static_cast<long double>(mach_absolute_time())*numer/denom);}
};
OSStatus render(Context* c,BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* b)noexcept{
    c->inRender.fetch_add(1);phase58InCallback=true;const auto start=c->now();
#ifdef PHASE59_FIX_STARTUP
    const auto entry=c->renderEntryCalls.fetch_add(1,std::memory_order_relaxed);
    if(entry<c->renderEntries.size()){
        const auto flags=stamp?stamp->mFlags:0;
        const auto host=stamp&&(flags&kAudioTimeStampHostTimeValid)?std::uint64_t(static_cast<long double>(stamp->mHostTime)*c->numer/c->denom):0;
        c->renderEntries[entry]={start,host,stamp?stamp->mSampleTime:0,n,flags,c->active.load()};
    }
#endif
    bool valid=b->mNumberBuffers==c->channels;float* p[2]{};
    for(unsigned i=0;i<b->mNumberBuffers;++i){auto& v=b->mBuffers[i];if(i<2)p[i]=static_cast<float*>(v.mData);valid&=v.mData&&v.mNumberChannels==1&&v.mDataByteSize>=n*sizeof(float);}
    phase58::RenderResult raw;
    if(c->active.load()&&valid){
        raw=c->pipeline->pullAudio(p,n);
        // Reference was read and touched before rendering. No file IO or hash in callback.
        for(std::size_t i=0;i<raw.received;++i)for(std::size_t ch=0;ch<c->channels;++ch){
            const auto frame=raw.outputBefore+i;const auto actual=std::bit_cast<std::uint32_t>(p[ch][i]);
            if(c->capture){if(frame<c->referenceFrames)c->capture[frame*c->channels+ch]=p[ch][i];else ++c->mismatches;continue;}
            const auto expected=frame<c->referenceFrames?std::bit_cast<std::uint32_t>(c->reference[frame*c->channels+ch]):0;
            if(frame>=c->referenceFrames||actual!=expected){if(!c->mismatches){c->firstMismatch=frame;c->actualBits=actual;c->expectedBits=expected;}++c->mismatches;}
        }
        if(raw.received&&!c->firstPcm)c->firstPcm=start;
        const auto flags=stamp?stamp->mFlags:0;const auto host=stamp&&(flags&kAudioTimeStampHostTimeValid)?std::uint64_t(static_cast<long double>(stamp->mHostTime)*c->numer/c->denom):0;
        const auto sample=stamp?stamp->mSampleTime:0;const auto io=c->now();
        auto evidence=c->clock.observe(c->epoch,start,io,host!=0,host,flags&kAudioTimeStampSampleTimeValid,sample,n,c->rate);
        c->hostMissing+=evidence.hostMissing;c->hostBackwards+=evidence.hostBackwards;c->hostCadence+=evidence.cadenceError||evidence.offsetOutlier;c->sampleErrors+=evidence.sampleError;c->sampleValid+=(flags&kAudioTimeStampSampleTimeValid)!=0;
        if(raw.received)c->lastTarget=(host?host:io)+std::uint64_t(raw.received*1e9/c->rate);
        Record* record=nullptr;if(c->calls<c->records.size()){record=&c->records[c->calls];*record={start,0,host,c->epoch,sample,flags,n,raw};}else ++c->dropped;++c->calls;
        const auto end=c->now();if(record)record->end=end;
        c->halMisses+=host&&end>host+std::max(100000.,2e9/c->rate);c->deadlines+=end-start>n*1e9/c->rate;c->maximum=std::max(c->maximum,end-start);
    }else{
        for(unsigned i=0;i<b->mNumberBuffers;++i)if(b->mBuffers[i].mData)std::memset(b->mBuffers[i].mData,0,b->mBuffers[i].mDataByteSize);
        if(c->active.load()&&!valid)++c->formats;
    }
    *silent=raw.received==0;phase58InCallback=false;c->inRender.fetch_sub(1);return noErr;
}
AudioDeviceID defaultDevice(){AudioDeviceID v=0;UInt32 n=sizeof(v);AudioObjectPropertyAddress a{kAudioHardwarePropertyDefaultOutputDevice,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,nullptr,&n,&v)!=noErr||!v)throw std::runtime_error("No default output device");return v;}
#ifdef PHASE59_FIX_STARTUP
OSStatus outputNotify(void* raw,AudioUnitRenderActionFlags* action,const AudioTimeStamp* stamp,UInt32 bus,UInt32 frames,AudioBufferList*)noexcept{
    auto* c=static_cast<Context*>(raw);c->inRender.fetch_add(1);const bool previous=phase58InCallback;phase58InCallback=true;
    const auto index=c->outputCalls.fetch_add(1);
    if(index<c->outputRecords.size()){
        const auto host=stamp&&(stamp->mFlags&kAudioTimeStampHostTimeValid)?std::uint64_t(static_cast<long double>(stamp->mHostTime)*c->numer/c->denom):0;
        c->outputRecords[index]={c->now(),host,stamp?stamp->mSampleTime:0,frames,action?*action:0,stamp?stamp->mFlags:0,bus};
    }
    phase58InCallback=previous;c->inRender.fetch_sub(1);return noErr;
}
#endif
unsigned bufferFrames(AudioDeviceID device){UInt32 v=0,n=sizeof(v);AudioObjectPropertyAddress a{kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(device,&a,0,nullptr,&n,&v)!=noErr)throw std::runtime_error("Device buffer unavailable");return v;}
struct Load {
    std::atomic<bool> stop{false};std::vector<std::thread> threads;std::vector<unsigned char> memory;
    Load(unsigned cpus,unsigned mib):memory(std::size_t(mib)*1024*1024,1){for(unsigned i=0;i<cpus;++i)threads.emplace_back([this]{volatile double v=.1;while(!stop.load()){for(unsigned i=0;i<10000;++i)v=std::sin(v+.001);}});}
    ~Load(){stop=true;for(auto& t:threads)t.join();}
};
struct OutputLifetime {
#ifdef PHASE59_FIX_STARTUP
    AudioUnit outputUnit=nullptr;
#endif
    Context* context;AVAudioEngine* audio=nil;AVAudioSourceNode* source=nil;id observer=nil;
    explicit OutputLifetime(Context* c):context(c){}
    void stop(){context->active=false;if(audio)[audio stop];
#ifdef PHASE59_FIX_STARTUP
        if(outputUnit){AudioUnitRemoveRenderNotify(outputUnit,outputNotify,context);outputUnit=nullptr;}
#endif
        while(context->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(context->pipeline)context->pipeline->setRealtimeRendering(false);
        if(observer)[[NSNotificationCenter defaultCenter]removeObserver:observer];observer=nil;
        if(audio&&source)[audio detachNode:source];source=nil;audio=nil;}
    ~OutputLifetime(){stop();}
};
}
int runOne(int argc,char** argv){@autoreleasepool{try{
    if(argc<10)throw std::invalid_argument("input speed_micros preset ref.f32 frames sha output normal|pause|route window_s [cpu_threads memory_mib analysis_delay_ms dsp_delay_ms]");
    const std::filesystem::path out=argv[7];if(std::filesystem::exists(out))throw std::runtime_error("Fresh output directory required");std::filesystem::create_directories(out);
    phase58::Configuration config;config.recordWorkerProfile=true;config.speedMicros=std::stoul(argv[2]);const std::string preset=argv[3],mode=argv[8];
    bool captureMode=false;std::filesystem::path capturePath,requestPath;
#ifdef PHASE59_FIX_STARTUP
    bool captureOutputNotify=false;
#endif
#ifdef PHASE59_RESEARCH
    config.dynamicTransitions=true;config.scheduling=phase58::WorkerScheduling::AudioWorkgroup;config.residentInput=true;
    captureMode=std::string(argv[4])=="capture";
#endif
    if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("preset");if(mode!="normal"&&mode!="pause"&&mode!="route")throw std::invalid_argument("mode");config.candidate=preset=="candidate";
    const auto expectedFrames=std::size_t(std::stoull(argv[5]));const double window=std::stod(argv[9]);const unsigned cpu=argc>10?std::stoul(argv[10]):0,memory=argc>11?std::stoul(argv[11]):0;
    if(cpu>8||memory>512||window<0||!std::isfinite(window))throw std::invalid_argument("Bounded probe load/window required");
    if(argc>12)config.analysisDelayMs=std::stod(argv[12]);if(argc>13)config.dspDelayMs=std::stod(argv[13]);
    std::string profileMode="block";
    for(int i=14;i<argc;++i){const std::string flag=argv[i];
        if(flag.starts_with("--profile=")){profileMode=flag.substr(10);if(profileMode!="off"&&profileMode!="block"&&profileMode!="detail")throw std::invalid_argument("profile mode");}
        else if(flag=="--sample-thread=on")config.sampleDspThread=true;
        else if(flag=="--sample-thread=off")config.sampleDspThread=false;
        else if(flag=="--worker=workgroup")config.scheduling=phase58::WorkerScheduling::AudioWorkgroup;
        else if(flag=="--worker=standard")config.scheduling=phase58::WorkerScheduling::Standard;
        else if(flag=="--resident-input=on")config.residentInput=true;
        else if(flag=="--resident-input=off")config.residentInput=false;
#ifdef PHASE59_FIX_STARTUP
        else if(flag=="--output-notify=on")captureOutputNotify=true;
        else if(flag.starts_with("--phase-probe=")){
            const auto colon=flag.find(':',14);if(colon==std::string::npos||config.phaseProbeWindowCount==config.phaseProbeWindows.size())throw std::invalid_argument("Bounded phase probe windows required");
            const auto first=std::stoull(flag.substr(14,colon-14)),last=std::stoull(flag.substr(colon+1));
            if(first>=last)throw std::invalid_argument("Invalid phase probe window");
            config.phaseProbeWindows[config.phaseProbeWindowCount++]={first,last};
        }
#endif
#ifdef PHASE59_RESEARCH
        else if(flag.starts_with("--capture-path="))capturePath=flag.substr(15);
        else if(flag.starts_with("--speed-requests="))requestPath=flag.substr(17);
        else if(flag=="--plan-failure=processing")config.transitionFailureForTest=1;
        else if(flag=="--plan-failure=allocation")config.transitionFailureForTest=2;
#endif
        else if(!flag.starts_with("--sessions="))throw std::invalid_argument("Unknown native probe option");
    }
    config.recordWorkerProfile=profileMode!="off";config.detailedDiagnostics=profileMode=="detail";
    ts::WavStreamReader metadata(argv[1]);
    if(!metadata.channels()||expectedFrames>(512ULL*1024*1024)/(metadata.channels()*sizeof(float)))throw std::length_error("Probe PCM budget exceeded");
    std::vector<float> reference(expectedFrames*metadata.channels());
    if(!captureMode){std::ifstream raw(argv[4],std::ios::binary);if(!raw.read(reinterpret_cast<char*>(reference.data()),reference.size()*sizeof(float))||raw.peek()!=EOF)throw std::runtime_error("Reference size mismatch");
        Phase45PcmDigest digest;digest.update(reference.data(),reference.size()*sizeof(float));if(digest.finish()!=argv[6])throw std::runtime_error("Reference SHA differs");}
    else if(capturePath.empty()||requestPath.empty())throw std::invalid_argument("Bounded capture path and speed request file required");
    Load load(cpu,memory);const auto processCpu=[](){rusage u{};getrusage(RUSAGE_SELF,&u);return u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6;};const auto cpuStart=processCpu();phase58::RealtimePipeline pipeline(argv[1],config);Context ctx;ctx.pipeline=&pipeline;ctx.reference=reference.data();ctx.referenceFrames=expectedFrames;ctx.rate=pipeline.sampleRate();ctx.channels=pipeline.channels();ctx.records.resize(262144);
    if(captureMode)ctx.capture=reference.data();
#ifdef PHASE59_RESEARCH
    const auto requests=phase59::readOperations(requestPath);std::size_t nextRequest=0;
#endif
    OutputLifetime lifetime(&ctx);mach_timebase_info_data_t tb{};mach_timebase_info(&tb);ctx.numer=tb.numer;ctx.denom=tb.denom;
#ifdef PHASE59_FIX_STARTUP
    struct StartupMark {const char* name;std::uint64_t ns;};
    std::array<StartupMark,16> startupMarks{};std::size_t startupCount=0;
    auto* entryBytes=reinterpret_cast<volatile unsigned char*>(ctx.renderEntries.data());
    for(std::size_t i=0;i<sizeof(ctx.renderEntries);++i)entryBytes[i]=0;
    const auto startupMark=[&](const char* name){startupMarks[startupCount++]={name,ctx.now()};};
    startupMark("pipeline_start_request");
#else
    const auto startupMark=[](const char*){};
#endif
    const auto allocationBase=phase58Allocations.load();const auto bridgeBefore=pipeline.elapsedSeconds();const auto bridgeMach=ctx.now();const auto bridgeAfter=pipeline.elapsedSeconds();const auto bridgeElapsed=(bridgeBefore+bridgeAfter)/2;const auto bridgeUncertainty=bridgeAfter-bridgeBefore;pipeline.start();
    startupMark("engine_construct_request");
    AVAudioEngine* audio=[[AVAudioEngine alloc]init];lifetime.audio=audio;startupMark("engine_construct_return");const auto device=defaultDevice();auto deviceFormat=[audio.outputNode outputFormatForBus:0];const double deviceRate=deviceFormat.sampleRate;const auto deviceChannels=deviceFormat.channelCount;const auto buffer=bufferFrames(device);
    startupMark("device_format_resolved");
    auto format=[[AVAudioFormat alloc]initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:ctx.rate channels:static_cast<AVAudioChannelCount>(ctx.channels) interleaved:NO];
    Context* state=&ctx;auto source=[[AVAudioSourceNode alloc]initWithFormat:format renderBlock:^OSStatus(BOOL* s,const AudioTimeStamp* t,AVAudioFrameCount n,AudioBufferList* b){return render(state,s,t,n,b);}];
    lifetime.source=source;[audio attachNode:source];[audio connect:source to:audio.mainMixerNode format:format];audio.mainMixerNode.outputVolume=.5f;
    startupMark("nodes_connected");startupMark("engine_prepare_request");[audio prepare];startupMark("engine_prepare_return");
#ifdef PHASE59_FIX_STARTUP
    if(captureOutputNotify){
        auto* bytes=reinterpret_cast<volatile unsigned char*>(ctx.outputRecords.data());
        for(std::size_t i=0;i<sizeof(ctx.outputRecords);++i)bytes[i]=0;
        ctx.captureOutputNotify=true;lifetime.outputUnit=audio.outputNode.audioUnit;
        if(!lifetime.outputUnit||AudioUnitAddRenderNotify(lifetime.outputUnit,outputNotify,&ctx)!=noErr)throw std::runtime_error("Output render notification unavailable");
    }
#endif
    // A notification already being delivered can outlive removeObserver. Its
    // flag has independent ownership and never dereferences a destroyed Context.
    auto routeSignal=std::make_shared<std::atomic<bool>>(false);
    id observer=[[NSNotificationCenter defaultCenter]addObserverForName:AVAudioEngineConfigurationChangeNotification object:audio queue:nil usingBlock:^(NSNotification*){routeSignal->store(true);}];
    lifetime.observer=observer;
    const auto configured=pipeline.elapsedSeconds();startupMark("ready_wait_request");if(!pipeline.waitUntilReady(std::chrono::seconds(60)))throw std::runtime_error("Preparation failed: "+pipeline.diagnostics().error);
    startupMark("ready_observed");
    const auto playRequested=pipeline.elapsedSeconds();const bool realtimeNeeded=!pipeline.finished();
    if(!pipeline.setRealtimeRendering(true))throw std::runtime_error("Realtime worker arming failed");
    startupMark("workgroup_armed");
    const auto realtimeArmed=pipeline.elapsedSeconds();ctx.active=true;NSError* error=nil;startupMark("engine_start_request");if(![audio startAndReturnError:&error])throw std::runtime_error(error?[[error description]UTF8String]:"Audio start failed");startupMark("engine_start_return");const auto audioStarted=pipeline.elapsedSeconds();
    const auto playbackStart=ctx.now();bool paused=false,resumed=false,routeStopped=false,timedOut=false,windowed=false;
    while(true){const double elapsed=double(ctx.now()-playbackStart)*1e-9;
        if(pipeline.failed())break;
#ifdef PHASE59_RESEARCH
        const auto position=pipeline.diagnostics().consumed;
        while(nextRequest<requests.size()&&requests[nextRequest].at<=position){pipeline.requestSpeed(requests[nextRequest].target,position);++nextRequest;}
#endif
        if(mode=="pause"&&!paused&&elapsed>=.5){ctx.active=false;[audio pause];while(ctx.inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));pipeline.setRealtimeRendering(false);paused=true;std::this_thread::sleep_for(std::chrono::milliseconds(200));++ctx.epoch;if(!pipeline.setRealtimeRendering(true))throw std::runtime_error("Realtime resume arming failed");ctx.active=true;if(![audio startAndReturnError:&error])throw std::runtime_error("Resume failed");resumed=true;}
        if(mode=="route"&&elapsed>=.5){[[NSNotificationCenter defaultCenter]postNotificationName:AVAudioEngineConfigurationChangeNotification object:audio];routeStopped=true;break;}
        if(routeSignal->exchange(false)){auto f=[audio.outputNode outputFormatForBus:0];if(defaultDevice()!=device||f.sampleRate!=deviceRate||f.channelCount!=deviceChannels){routeStopped=true;break;}}
        if(pipeline.drained()&&ctx.now()>=ctx.lastTarget.load()+5000000)break;
        if(window>0&&elapsed>=window){windowed=true;break;}
        if(elapsed>expectedFrames/ctx.rate*2+30){timedOut=true;break;}
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    lifetime.stop();pipeline.stop();const auto captureEnded=pipeline.elapsedSeconds();const auto d=pipeline.diagnostics();const auto callbackAllocations=phase58Allocations.load()-allocationBase;
#ifdef PHASE59_RESEARCH
    phase59::exportOperations(out,pipeline.speedOperations(),config.speedMicros);
    if(config.dynamicTransitions){const auto map=pipeline.dynamicTimeMap();std::ofstream nodes(out/"dynamic_map.nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(map.starts().data()),map.starts().size()*sizeof(long long));
        std::ofstream events(out/"dynamic_events.csv");events<<"onset,peak,attack_end,end,strength_bits\n";for(const auto& e:map.events())events<<e.onsetFrame<<','<<e.peakFrame<<','<<e.attackEndFrame<<','<<e.endFrame<<','<<std::bit_cast<std::uint32_t>(e.strength)<<'\n';}
    if(captureMode){std::ofstream captured(capturePath,std::ios::binary|std::ios::trunc);if(!captured.write(reinterpret_cast<const char*>(reference.data()),std::min(d.consumed,expectedFrames)*ctx.channels*sizeof(float)))throw std::runtime_error("Capture write failed");}
#endif
    std::ofstream detailCsv(out/"detail.csv");detailCsv<<"stage,scope,begin,at_s,cpu_s,cpp_new_calls\n"<<std::setprecision(17);
    for(const auto& e:pipeline.detailEvents())detailCsv<<e.stage<<','<<e.scope<<','<<e.begin<<','<<e.atS<<','<<e.cpuS<<','<<e.newCalls<<'\n';
    std::ofstream sampleCsv(out/"thread_samples.csv");sampleCsv<<"before_s,after_s,stage_before,stage_after,result,user_ns,system_ns,run_state,policy,current_priority,base_priority,max_priority\n"<<std::setprecision(17);
    for(const auto& s:pipeline.threadSamples()){
        sampleCsv<<s.beforeS<<','<<s.afterS<<','<<s.stageBefore<<','<<s.stageAfter<<','<<s.result<<',';
        if(s.result==KERN_SUCCESS)sampleCsv<<s.userNs<<','<<s.systemNs;else sampleCsv<<"null,null";
        sampleCsv<<','<<s.state<<','<<s.policy<<','<<s.currentPriority<<','<<s.basePriority<<','<<s.maxPriority<<'\n';
    }
    std::ofstream workerCsv(out/"worker.csv");workerCsv<<"output_start,output_end,fifo_before,fifo_after,received_input,snapshot_version,final_snapshot,start_s,published_s,wall_s,cpu_s,publication_gap_s,wav_wall_s,wav_cpu_s,fft_wall_s,fft_cpu_s,phase_wall_s,phase_cpu_s,ola_wall_s,ola_cpu_s,fir_wall_s,fir_cpu_s,realtime\n"<<std::setprecision(17);
    for(const auto& r:pipeline.workerRecords()){workerCsv<<r.outputStart<<','<<r.outputEnd<<','<<r.fifoBefore<<','<<r.fifoAfter<<','<<r.receivedInput<<','<<r.snapshotVersion<<','<<r.finalSnapshot<<','<<r.startedS<<','<<r.publishedS<<','<<r.wallS<<','<<r.cpuS<<','<<r.publicationGapS;for(const auto& t:r.work.stages)workerCsv<<','<<t.wallSeconds<<','<<t.threadCpuSeconds;workerCsv<<','<<r.realtime<<'\n';}
#ifdef PHASE59_FIX_STARTUP
    std::ofstream intervalCsv(out/"intervals.csv");intervalCsv<<"output_start,start_ticks,end_ticks,deadline_ticks,timebase_numer,timebase_denom,deadline_miss\n";
    for(const auto& r:pipeline.workerRecords())if(r.realtime){const auto& t=r.intervalTiming;intervalCsv<<r.outputStart<<','<<t.startTicks<<','<<t.endTicks<<','<<t.deadlineTicks<<','<<ctx.numer<<','<<ctx.denom<<','<<(t.endTicks>t.deadlineTicks)<<'\n';}
    std::ofstream framesCsv(out/"phase_frames.csv");framesCsv<<"output_start,resolution,frames,shared_peaks,max_shared_peaks,resets,first_input,last_input,neighborhood_evaluations\n";
    for(const auto& r:pipeline.workerRecords())for(std::size_t resolution=0;resolution<3;++resolution){const auto& f=r.work.phaseFrames[resolution];framesCsv<<r.outputStart<<','<<resolution<<','<<f.frames<<','<<f.sharedPeaks<<','<<f.maxSharedPeaks<<','<<f.resets<<','<<f.firstInput<<','<<f.lastInput<<','<<f.neighborhoodEvaluations<<'\n';}
#endif
    std::ofstream csv(out/"callbacks.csv");csv<<"sequence,epoch,start_ns,end_ns,host_ns,sample_time,flags,requested,wanted,received,output_before,fifo_before\n"<<std::setprecision(17);std::vector<std::uint64_t> durations;
    for(std::size_t i=0;i<std::min<std::size_t>(ctx.calls,ctx.records.size());++i){const auto& r=ctx.records[i];durations.push_back(r.end-r.start);csv<<i+1<<','<<r.epoch<<','<<r.start<<','<<r.end<<','<<r.host<<','<<r.sample<<','<<r.flags<<','<<r.frames<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.fifoBefore<<'\n';}
    std::sort(durations.begin(),durations.end());const auto percentile=[&](double q){return durations.empty()?0:durations[std::min(durations.size()-1,std::size_t(std::ceil(q*durations.size())-1))];};
#ifdef PHASE59_FIX_STARTUP
    std::ofstream startupCsv(out/"startup.csv");startupCsv<<"event,mach_ns\n";
    for(std::size_t i=0;i<startupCount;++i)startupCsv<<startupMarks[i].name<<','<<startupMarks[i].ns<<'\n';
    for(std::size_t i=0;i<std::min<std::size_t>(2,ctx.calls);++i)startupCsv<<"callback_"<<i+1<<','<<ctx.records[i].start<<'\n';
    std::ofstream entriesCsv(out/"initial_render_entries.csv");entriesCsv<<"sequence,start_ns,host_ns,sample_time,frames,timestamp_flags,active\n"<<std::setprecision(17);
    for(std::size_t i=0;i<std::min<std::size_t>(ctx.renderEntryCalls.load(),ctx.renderEntries.size());++i){const auto& r=ctx.renderEntries[i];entriesCsv<<i+1<<','<<r.start<<','<<r.host<<','<<r.sample<<','<<r.frames<<','<<r.flags<<','<<r.active<<'\n';}
    if(captureOutputNotify){
        std::ofstream notifyCsv(out/"output_notify.csv");notifyCsv<<"sequence,start_ns,host_ns,sample_time,frames,action_flags,timestamp_flags,bus\n"<<std::setprecision(17);
        for(std::size_t i=0;i<std::min<std::size_t>(ctx.outputCalls.load(),ctx.outputRecords.size());++i){const auto& r=ctx.outputRecords[i];notifyCsv<<i+1<<','<<r.start<<','<<r.host<<','<<r.sample<<','<<r.frames<<','<<r.action<<','<<r.flags<<','<<r.bus<<'\n';}
    }
#endif
    const bool eos=d.dspDone&&d.consumed==(captureMode?d.outputFrames:expectedFrames),pcm=ctx.calls&&!ctx.mismatches&&d.consumed>0;
    const bool measured=ctx.calls>1&&!ctx.dropped&&ctx.sampleValid==ctx.calls&&!ctx.hostMissing&&!ctx.hostBackwards&&!ctx.hostCadence&&!ctx.sampleErrors&&!ctx.halMisses;
    const bool audioPass=pcm&&!d.missingFrames&&!d.missingCalls&&!d.rejectedWrites&&!ctx.deadlines&&!ctx.formats&&!callbackAllocations&&!d.failed&&!timedOut;
    const auto& rt=d.scheduling;const bool schedulingValid=!rt.enabled||((!realtimeNeeded||rt.policyMeasured)&&!rt.policyErrors&&!rt.joinErrors&&!rt.restoreErrors&&!rt.intervalErrors&&!rt.queryErrors&&!rt.waitErrors&&!rt.wakeErrors&&rt.promotions==rt.joins&&rt.joins==rt.leaves&&rt.leaves==rt.restores&&rt.intervalStarts==rt.intervalFinishes&&!rt.active);
    const bool realtimeAllocationValid=!rt.enabled||!realtimeNeeded||(d.realtimeAllocationsMeasured&&!d.realtimeNewCalls);
    const bool pass=audioPass&&measured&&schedulingValid&&realtimeAllocationValid&&!rt.deadlineMisses&&(eos||windowed||routeStopped)&&(mode!="pause"||(paused&&resumed));
    rusage usage{};getrusage(RUSAGE_SELF,&usage);std::ofstream result(out/"summary.json");result<<std::setprecision(17)<<"{\"PASS\":"<<(pass?"true":"false")<<",\"audio_pass\":"<<audioPass<<",\"measurement_valid\":"<<measured<<",\"capture_mode\":"<<captureMode<<",\"pcm_prefix_exact\":"<<(!captureMode&&pcm)<<",\"pcm_complete_exact\":"<<(!captureMode&&pcm&&eos&&d.pcmSha256==argv[6])<<",\"eos\":"<<eos<<",\"windowed\":"<<windowed<<",\"route_stopped\":"<<routeStopped<<",\"route_simulated\":"<<(mode=="route")<<",\"paused_resumed\":"<<(paused&&resumed)
        <<",\"preset\":"<<phase58::jsonString(preset)<<",\"speed_micros\":"<<config.speedMicros<<",\"device_id\":"<<device<<",\"device_rate\":"<<deviceRate<<",\"device_channels\":"<<deviceChannels<<",\"device_buffer_frames\":"<<buffer<<",\"input_rate\":"<<ctx.rate<<",\"channels\":"<<ctx.channels<<",\"cpu_load_threads\":"<<cpu<<",\"memory_load_mib\":"<<memory
        <<",\"callback_calls\":"<<ctx.calls<<",\"callback_max_ns\":"<<ctx.maximum<<",\"callback_p95_ns\":"<<percentile(.95)<<",\"callback_p99_ns\":"<<percentile(.99)<<",\"callback_deadlines\":"<<ctx.deadlines<<",\"callback_formats\":"<<ctx.formats<<",\"callback_records_dropped\":"<<ctx.dropped<<",\"callback_cpp_allocations\":"<<callbackAllocations<<",\"allocation_measured\":true,\"host_missing\":"<<ctx.hostMissing<<",\"host_backwards\":"<<ctx.hostBackwards<<",\"host_cadence_errors\":"<<ctx.hostCadence<<",\"sample_errors\":"<<ctx.sampleErrors<<",\"sample_valid_calls\":"<<ctx.sampleValid<<",\"hal_misses\":"<<ctx.halMisses
        <<",\"pcm_mismatches\":"<<ctx.mismatches<<",\"first_mismatch_frame\":"<<ctx.firstMismatch<<",\"actual_bits\":"<<ctx.actualBits<<",\"expected_bits\":"<<ctx.expectedBits<<",\"av_configured_s\":"<<configured<<",\"play_requested_s\":"<<playRequested<<",\"audio_started_s\":"<<audioStarted<<",\"first_callback_s\":"<<(ctx.firstPcm?bridgeElapsed+double(ctx.firstPcm-bridgeMach)*1e-9:-1)<<",\"bridge_uncertainty_s\":"<<bridgeUncertainty<<",\"startup_timing_valid\":"<<(ctx.firstPcm&&bridgeUncertainty<=.001)<<",\"wall_s\":"<<captureEnded<<",\"process_cpu_s\":"<<processCpu()-cpuStart<<",\"analysis_cache_hit\":false,\"peak_rss_bytes\":"<<usage.ru_maxrss<<",\"reference_bytes\":"<<(captureMode?0:reference.size()*sizeof(float))<<",\"capture_buffer_bytes\":"<<(captureMode?reference.size()*sizeof(float):0);
    result<<",\"profile_mode\":"<<phase58::jsonString(profileMode)<<",\"clock_mach_ns\":"<<bridgeMach<<",\"clock_pipeline_s\":"<<bridgeElapsed<<",\"realtime_armed_s\":"<<realtimeArmed<<",\"realtime_needed\":"<<realtimeNeeded<<",\"scheduling_valid\":"<<schedulingValid<<",\"realtime_allocation_valid\":"<<realtimeAllocationValid;
    phase58::writeDiagnostics(result,d);result<<"}\n";std::cout<<(pass?"PASS":"FAIL")<<" callback="<<ctx.calls<<" underrun="<<d.missingFrames<<" hal="<<ctx.halMisses<<" pcm="<<ctx.mismatches<<'\n';return pass?0:2;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}}
int main(int argc,char** argv){try{
    if(argc>9&&(std::string(argv[8])=="restart"||std::string(argv[8])=="repeat")){
        const bool repeat=std::string(argv[8])=="repeat";
        std::size_t count=repeat?20:2;
        for(int i=14;i<argc;++i)if(std::string(argv[i]).starts_with("--sessions="))count=std::stoul(std::string(argv[i]).substr(11));
        if(!count||count>1000||(!repeat&&count!=2))throw std::invalid_argument("Bounded repeated session count required");
        const std::filesystem::path root=argv[7];if(std::filesystem::exists(root))throw std::runtime_error("Fresh repeated output required");std::filesystem::create_directories(root);
        int status=0;for(std::size_t i=0;i<count;++i){
            const auto scope=repeat?"session_"+std::to_string(i):(i?std::string("restart"):std::string("cold"));
            std::vector<std::string> arguments(argv,argv+argc);arguments[7]=(root/scope).string();arguments[8]="normal";std::vector<char*> pointers;for(auto& a:arguments)pointers.push_back(a.data());pointers.push_back(nullptr);
            const auto result=runOne(argc,pointers.data());status=std::max(status,result);std::cout<<"SESSION "<<i<<" status="<<result<<std::endl;
        }return status;
    }
    return runOne(argc,argv);
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
