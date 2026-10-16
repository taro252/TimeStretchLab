#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#include "prototype/Phase58Diagnostics.h"
#include "prototype/Phase46HostClock.h"
#include "prototype/Phase45PcmDigest.h"
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
void* operator new(std::size_t n){if(phase58InCallback)++phase58Allocations;if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){if(phase58InCallback)++phase58Allocations;void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
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
    std::atomic<bool> active{false};std::atomic<unsigned> inRender{0};
    std::uint64_t numer=1,denom=1,epoch=1,calls=0,dropped=0,maximum=0,deadlines=0,formats=0;
    std::uint64_t hostMissing=0,hostBackwards=0,hostCadence=0,sampleErrors=0,sampleValid=0,halMisses=0;
    std::uint64_t mismatches=0,firstMismatch=0,firstPcm=0;std::atomic<std::uint64_t> lastTarget{0};std::uint32_t actualBits=0,expectedBits=0;
    std::vector<Record> records;Phase46HostClock clock;
    std::uint64_t now()const noexcept{return std::uint64_t(static_cast<long double>(mach_absolute_time())*numer/denom);}
};
OSStatus render(Context* c,BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* b)noexcept{
    c->inRender.fetch_add(1);phase58InCallback=true;const auto start=c->now();
    bool valid=b->mNumberBuffers==c->channels;float* p[2]{};
    for(unsigned i=0;i<b->mNumberBuffers;++i){auto& v=b->mBuffers[i];if(i<2)p[i]=static_cast<float*>(v.mData);valid&=v.mData&&v.mNumberChannels==1&&v.mDataByteSize>=n*sizeof(float);}
    phase58::RenderResult raw;
    if(c->active.load()&&valid){
        raw=c->pipeline->pullAudio(p,n);
        // Reference was read and touched before rendering. No file IO or hash in callback.
        for(std::size_t i=0;i<raw.received;++i)for(std::size_t ch=0;ch<c->channels;++ch){
            const auto frame=raw.outputBefore+i;const auto actual=std::bit_cast<std::uint32_t>(p[ch][i]);
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
unsigned bufferFrames(AudioDeviceID device){UInt32 v=0,n=sizeof(v);AudioObjectPropertyAddress a{kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(device,&a,0,nullptr,&n,&v)!=noErr)throw std::runtime_error("Device buffer unavailable");return v;}
struct Load {
    std::atomic<bool> stop{false};std::vector<std::thread> threads;std::vector<unsigned char> memory;
    Load(unsigned cpus,unsigned mib):memory(std::size_t(mib)*1024*1024,1){for(unsigned i=0;i<cpus;++i)threads.emplace_back([this]{volatile double v=.1;while(!stop.load()){for(unsigned i=0;i<10000;++i)v=std::sin(v+.001);}});}
    ~Load(){stop=true;for(auto& t:threads)t.join();}
};
struct OutputLifetime {
    Context* context;AVAudioEngine* audio=nil;AVAudioSourceNode* source=nil;id observer=nil;
    explicit OutputLifetime(Context* c):context(c){}
    void stop(){context->active=false;if(audio)[audio stop];while(context->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(observer)[[NSNotificationCenter defaultCenter]removeObserver:observer];observer=nil;
        if(audio&&source)[audio detachNode:source];source=nil;audio=nil;}
    ~OutputLifetime(){stop();}
};
}
int runOne(int argc,char** argv){@autoreleasepool{try{
    if(argc<10)throw std::invalid_argument("input speed_micros preset ref.f32 frames sha output normal|pause|route window_s [cpu_threads memory_mib analysis_delay_ms dsp_delay_ms]");
    const std::filesystem::path out=argv[7];if(std::filesystem::exists(out))throw std::runtime_error("Fresh output directory required");std::filesystem::create_directories(out);
    phase58::Configuration config;config.recordWorkerProfile=true;config.speedMicros=std::stoul(argv[2]);const std::string preset=argv[3],mode=argv[8];
    if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("preset");if(mode!="normal"&&mode!="pause"&&mode!="route")throw std::invalid_argument("mode");config.candidate=preset=="candidate";
    const auto expectedFrames=std::stoull(argv[5]);const double window=std::stod(argv[9]);const unsigned cpu=argc>10?std::stoul(argv[10]):0,memory=argc>11?std::stoul(argv[11]):0;
    if(cpu>8||memory>512||window<0||!std::isfinite(window))throw std::invalid_argument("Bounded probe load/window required");
    if(argc>12)config.analysisDelayMs=std::stod(argv[12]);if(argc>13)config.dspDelayMs=std::stod(argv[13]);
    ts::WavStreamReader metadata(argv[1]);std::vector<float> reference(expectedFrames*metadata.channels());
    std::ifstream raw(argv[4],std::ios::binary);if(!raw.read(reinterpret_cast<char*>(reference.data()),reference.size()*sizeof(float))||raw.peek()!=EOF)throw std::runtime_error("Reference size mismatch");
    Phase45PcmDigest digest;digest.update(reference.data(),reference.size()*sizeof(float));if(digest.finish()!=argv[6])throw std::runtime_error("Reference SHA differs");
    Load load(cpu,memory);const auto processCpu=[](){rusage u{};getrusage(RUSAGE_SELF,&u);return u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6;};const auto cpuStart=processCpu();phase58::RealtimePipeline pipeline(argv[1],config);Context ctx;ctx.pipeline=&pipeline;ctx.reference=reference.data();ctx.referenceFrames=expectedFrames;ctx.rate=pipeline.sampleRate();ctx.channels=pipeline.channels();ctx.records.resize(262144);
    OutputLifetime lifetime(&ctx);mach_timebase_info_data_t tb{};mach_timebase_info(&tb);ctx.numer=tb.numer;ctx.denom=tb.denom;
    const auto allocationBase=phase58Allocations.load();const auto bridgeBefore=pipeline.elapsedSeconds();const auto bridgeMach=ctx.now();const auto bridgeAfter=pipeline.elapsedSeconds();const auto bridgeElapsed=(bridgeBefore+bridgeAfter)/2;const auto bridgeUncertainty=bridgeAfter-bridgeBefore;pipeline.start();
    AVAudioEngine* audio=[[AVAudioEngine alloc]init];lifetime.audio=audio;const auto device=defaultDevice();auto deviceFormat=[audio.outputNode outputFormatForBus:0];const double deviceRate=deviceFormat.sampleRate;const auto deviceChannels=deviceFormat.channelCount;const auto buffer=bufferFrames(device);
    auto format=[[AVAudioFormat alloc]initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:ctx.rate channels:static_cast<AVAudioChannelCount>(ctx.channels) interleaved:NO];
    Context* state=&ctx;auto source=[[AVAudioSourceNode alloc]initWithFormat:format renderBlock:^OSStatus(BOOL* s,const AudioTimeStamp* t,AVAudioFrameCount n,AudioBufferList* b){return render(state,s,t,n,b);}];
    lifetime.source=source;[audio attachNode:source];[audio connect:source to:audio.mainMixerNode format:format];audio.mainMixerNode.outputVolume=.5f;[audio prepare];
    // A notification already being delivered can outlive removeObserver. Its
    // flag has independent ownership and never dereferences a destroyed Context.
    auto routeSignal=std::make_shared<std::atomic<bool>>(false);
    id observer=[[NSNotificationCenter defaultCenter]addObserverForName:AVAudioEngineConfigurationChangeNotification object:audio queue:nil usingBlock:^(NSNotification*){routeSignal->store(true);}];
    lifetime.observer=observer;
    const auto configured=pipeline.elapsedSeconds();if(!pipeline.waitUntilReady(std::chrono::seconds(60)))throw std::runtime_error("Preparation failed: "+pipeline.diagnostics().error);
    const auto playRequested=pipeline.elapsedSeconds();ctx.active=true;NSError* error=nil;if(![audio startAndReturnError:&error])throw std::runtime_error(error?[[error description]UTF8String]:"Audio start failed");const auto audioStarted=pipeline.elapsedSeconds();
    const auto playbackStart=ctx.now();bool paused=false,resumed=false,routeStopped=false,timedOut=false,windowed=false;
    while(true){const double elapsed=double(ctx.now()-playbackStart)*1e-9;
        if(pipeline.failed())break;
        if(mode=="pause"&&!paused&&elapsed>=.5){ctx.active=false;[audio pause];while(ctx.inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));paused=true;std::this_thread::sleep_for(std::chrono::milliseconds(200));++ctx.epoch;ctx.active=true;if(![audio startAndReturnError:&error])throw std::runtime_error("Resume failed");resumed=true;}
        if(mode=="route"&&elapsed>=.5){[[NSNotificationCenter defaultCenter]postNotificationName:AVAudioEngineConfigurationChangeNotification object:audio];routeStopped=true;break;}
        if(routeSignal->exchange(false)){auto f=[audio.outputNode outputFormatForBus:0];if(defaultDevice()!=device||f.sampleRate!=deviceRate||f.channelCount!=deviceChannels){routeStopped=true;break;}}
        if(pipeline.drained()&&ctx.now()>=ctx.lastTarget.load()+5000000)break;
        if(window>0&&elapsed>=window){windowed=true;break;}
        if(elapsed>expectedFrames/ctx.rate*2+30){timedOut=true;break;}
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    lifetime.stop();pipeline.stop();const auto captureEnded=pipeline.elapsedSeconds();const auto d=pipeline.diagnostics();const auto callbackAllocations=phase58Allocations.load()-allocationBase;
    std::ofstream workerCsv(out/"worker.csv");workerCsv<<"output_start,output_end,fifo_before,fifo_after,received_input,snapshot_version,final_snapshot,start_s,published_s,wall_s,cpu_s,publication_gap_s,wav_wall_s,wav_cpu_s,fft_wall_s,fft_cpu_s,phase_wall_s,phase_cpu_s,ola_wall_s,ola_cpu_s,fir_wall_s,fir_cpu_s\n"<<std::setprecision(17);
    for(const auto& r:pipeline.workerRecords()){workerCsv<<r.outputStart<<','<<r.outputEnd<<','<<r.fifoBefore<<','<<r.fifoAfter<<','<<r.receivedInput<<','<<r.snapshotVersion<<','<<r.finalSnapshot<<','<<r.startedS<<','<<r.publishedS<<','<<r.wallS<<','<<r.cpuS<<','<<r.publicationGapS;for(const auto& t:r.work.stages)workerCsv<<','<<t.wallSeconds<<','<<t.threadCpuSeconds;workerCsv<<'\n';}
    std::ofstream csv(out/"callbacks.csv");csv<<"sequence,epoch,start_ns,end_ns,host_ns,sample_time,flags,requested,wanted,received,output_before,fifo_before\n"<<std::setprecision(17);std::vector<std::uint64_t> durations;
    for(std::size_t i=0;i<std::min<std::size_t>(ctx.calls,ctx.records.size());++i){const auto& r=ctx.records[i];durations.push_back(r.end-r.start);csv<<i+1<<','<<r.epoch<<','<<r.start<<','<<r.end<<','<<r.host<<','<<r.sample<<','<<r.flags<<','<<r.frames<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.fifoBefore<<'\n';}
    std::sort(durations.begin(),durations.end());const auto percentile=[&](double q){return durations.empty()?0:durations[std::min(durations.size()-1,std::size_t(std::ceil(q*durations.size())-1))];};
    const bool eos=d.dspDone&&d.consumed==expectedFrames,pcm=ctx.calls&&!ctx.mismatches&&d.consumed>0;
    const bool measured=ctx.calls>1&&!ctx.dropped&&ctx.sampleValid==ctx.calls&&!ctx.hostMissing&&!ctx.hostBackwards&&!ctx.hostCadence&&!ctx.sampleErrors&&!ctx.halMisses;
    const bool audioPass=pcm&&!d.missingFrames&&!d.missingCalls&&!d.rejectedWrites&&!ctx.deadlines&&!ctx.formats&&!callbackAllocations&&!d.failed&&!timedOut;
    const bool pass=audioPass&&measured&&(eos||windowed||routeStopped)&&(mode!="pause"||(paused&&resumed));
    rusage usage{};getrusage(RUSAGE_SELF,&usage);std::ofstream result(out/"summary.json");result<<std::setprecision(17)<<"{\"PASS\":"<<(pass?"true":"false")<<",\"audio_pass\":"<<audioPass<<",\"measurement_valid\":"<<measured<<",\"pcm_prefix_exact\":"<<pcm<<",\"pcm_complete_exact\":"<<(pcm&&eos&&d.pcmSha256==argv[6])<<",\"eos\":"<<eos<<",\"windowed\":"<<windowed<<",\"route_stopped\":"<<routeStopped<<",\"route_simulated\":"<<(mode=="route")<<",\"paused_resumed\":"<<(paused&&resumed)
        <<",\"preset\":"<<phase58::jsonString(preset)<<",\"speed_micros\":"<<config.speedMicros<<",\"device_id\":"<<device<<",\"device_rate\":"<<deviceRate<<",\"device_channels\":"<<deviceChannels<<",\"device_buffer_frames\":"<<buffer<<",\"input_rate\":"<<ctx.rate<<",\"channels\":"<<ctx.channels<<",\"cpu_load_threads\":"<<cpu<<",\"memory_load_mib\":"<<memory
        <<",\"callback_calls\":"<<ctx.calls<<",\"callback_max_ns\":"<<ctx.maximum<<",\"callback_p95_ns\":"<<percentile(.95)<<",\"callback_p99_ns\":"<<percentile(.99)<<",\"callback_deadlines\":"<<ctx.deadlines<<",\"callback_formats\":"<<ctx.formats<<",\"callback_records_dropped\":"<<ctx.dropped<<",\"callback_cpp_allocations\":"<<callbackAllocations<<",\"allocation_measured\":true,\"host_missing\":"<<ctx.hostMissing<<",\"host_backwards\":"<<ctx.hostBackwards<<",\"host_cadence_errors\":"<<ctx.hostCadence<<",\"sample_errors\":"<<ctx.sampleErrors<<",\"sample_valid_calls\":"<<ctx.sampleValid<<",\"hal_misses\":"<<ctx.halMisses
        <<",\"pcm_mismatches\":"<<ctx.mismatches<<",\"first_mismatch_frame\":"<<ctx.firstMismatch<<",\"actual_bits\":"<<ctx.actualBits<<",\"expected_bits\":"<<ctx.expectedBits<<",\"av_configured_s\":"<<configured<<",\"play_requested_s\":"<<playRequested<<",\"audio_started_s\":"<<audioStarted<<",\"first_callback_s\":"<<(ctx.firstPcm?bridgeElapsed+double(ctx.firstPcm-bridgeMach)*1e-9:-1)<<",\"bridge_uncertainty_s\":"<<bridgeUncertainty<<",\"startup_timing_valid\":"<<(ctx.firstPcm&&bridgeUncertainty<=.001)<<",\"wall_s\":"<<captureEnded<<",\"process_cpu_s\":"<<processCpu()-cpuStart<<",\"analysis_cache_hit\":false,\"peak_rss_bytes\":"<<usage.ru_maxrss<<",\"reference_bytes\":"<<reference.size()*sizeof(float);
    phase58::writeDiagnostics(result,d);result<<"}\n";std::cout<<(pass?"PASS":"FAIL")<<" callback="<<ctx.calls<<" underrun="<<d.missingFrames<<" hal="<<ctx.halMisses<<" pcm="<<ctx.mismatches<<'\n';return pass?0:2;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}}
int main(int argc,char** argv){try{
    if(argc>9&&std::string(argv[8])=="restart"){
        const std::filesystem::path root=argv[7];if(std::filesystem::exists(root))throw std::runtime_error("Fresh restart output required");std::filesystem::create_directories(root);
        int status=0;for(const auto* scope:{"cold","restart"}){
            std::vector<std::string> arguments(argv,argv+argc);arguments[7]=(root/scope).string();arguments[8]="normal";std::vector<char*> pointers;for(auto& a:arguments)pointers.push_back(a.data());pointers.push_back(nullptr);
            status=std::max(status,runOne(argc,pointers.data()));
        }return status;
    }
    return runOne(argc,argv);
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
