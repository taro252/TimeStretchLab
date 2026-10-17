#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#import <AudioUnit/AudioUnit.h>
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase46HostClock.h"
#include <mach/mach_time.h>
#include <pthread.h>
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>

// Independent fixed-PCM experiment. No analysis, TimeMap or synthesis is run.
namespace {
thread_local bool inCallback=false;
std::atomic<std::uint64_t> callbackNew{0};
void noteNew(){if(inCallback)callbackNew.fetch_add(1,std::memory_order_relaxed);}
}
void* operator new(std::size_t n){noteNew();if(auto* p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){noteNew();void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}
void operator delete(void* p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t)noexcept{std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}
void* operator new(std::size_t n,const std::nothrow_t&)noexcept{try{return ::operator new(n);}catch(...){return nullptr;}}
void* operator new[](std::size_t n,const std::nothrow_t&)noexcept{try{return ::operator new[](n);}catch(...){return nullptr;}}
void* operator new(std::size_t n,std::align_val_t a,const std::nothrow_t&)noexcept{try{return ::operator new(n,a);}catch(...){return nullptr;}}
void* operator new[](std::size_t n,std::align_val_t a,const std::nothrow_t&)noexcept{try{return ::operator new[](n,a);}catch(...){return nullptr;}}
void operator delete(void* p,const std::nothrow_t&)noexcept{std::free(p);}void operator delete[](void* p,const std::nothrow_t&)noexcept{std::free(p);}
void operator delete(void* p,std::align_val_t,const std::nothrow_t&)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t,const std::nothrow_t&)noexcept{std::free(p);}

namespace {
struct Row {
    std::uint64_t begin=0,end=0,host=0,logical=0,readBefore=0,readAfter=0,writeBefore=0,writeAfter=0;
    std::uint64_t thread=0;double sample=0,scalar=0;
    std::uint32_t flags=0,frames=0,received=0,fifoBefore=0,fifoAfter=0;
};
struct WriteRow {std::uint64_t begin=0,end=0,thread=0;std::size_t first=0,count=0,before=0,after=0;};
struct NotifyRow {std::uint64_t ticks=0,host=0;double sample=0,scalar=0;std::uint32_t frames=0,flags=0,action=0;};
struct Context {
    static constexpr double rate=48000;
    std::array<std::vector<float>,2> pcm;
    std::vector<Row> rows;
    std::vector<NotifyRow> notify;
    std::unique_ptr<ts::Phase14AudioFifo> fifo;
    std::size_t total=0,position=0,calls=0,notifyCalls=0;
    std::uint64_t numer=1,denom=1,missing=0,mismatch=0,formats=0,dropped=0;
    std::uint64_t sampleErrors=0,hostErrors=0,invalidHost=0,invalidSample=0,deadlines=0,halWindow=0;
    std::atomic<std::size_t> consumed{0};
    std::atomic<unsigned> inRender{0};
    ts::prototype::Phase46HostClock clock;
    std::uint64_t ns(std::uint64_t ticks)const noexcept{return std::uint64_t(static_cast<long double>(ticks)*numer/denom);}
};
template<class T>void touch(std::vector<T>& v){auto* p=reinterpret_cast<volatile unsigned char*>(v.data());for(std::size_t i=0;i<v.size()*sizeof(T);++i)p[i]=0;}
OSStatus render(Context* c,BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* buffers)noexcept{
    c->inRender.fetch_add(1);inCallback=true;Row r;r.begin=mach_absolute_time();pthread_threadid_np(nullptr,&r.thread);
    r.flags=stamp?stamp->mFlags:0;r.host=stamp?stamp->mHostTime:0;r.sample=stamp?stamp->mSampleTime:0;r.scalar=stamp?stamp->mRateScalar:0;
    r.frames=n;r.logical=c->position;
    bool valid=buffers->mNumberBuffers==2;float* output[2]{};
    for(unsigned ch=0;ch<buffers->mNumberBuffers;++ch){auto& b=buffers->mBuffers[ch];if(ch<2)output[ch]=static_cast<float*>(b.mData);valid&=b.mData&&b.mNumberChannels==1&&b.mDataByteSize>=n*sizeof(float);}
    if(valid){
        const auto wanted=std::min<std::size_t>(n,c->total-c->position);
        std::size_t got=wanted;
        if(c->fifo){
            r.readBefore=c->fifo->readPosition();r.writeBefore=c->fifo->writePosition();r.fifoBefore=c->fifo->available();
            got=c->fifo->read(output,wanted);
            r.readAfter=c->fifo->readPosition();r.writeAfter=c->fifo->writePosition();r.fifoAfter=c->fifo->available();
        }else{
            r.readBefore=c->position;r.writeBefore=c->total;r.fifoBefore=0;
            for(unsigned ch=0;ch<2;++ch)std::memcpy(output[ch],c->pcm[ch].data()+c->position,got*sizeof(float));
            r.readAfter=c->position+got;r.writeAfter=c->total;
        }
        for(unsigned ch=0;ch<2;++ch){
            for(std::size_t i=0;i<got;++i)c->mismatch+=std::bit_cast<std::uint32_t>(output[ch][i])!=std::bit_cast<std::uint32_t>(c->pcm[ch][c->position+i]);
            std::memset(output[ch]+got,0,(n-got)*sizeof(float));
        }
        r.received=got;c->missing+=wanted-got;c->position+=got;c->consumed.store(c->position,std::memory_order_release);
    }else{
        ++c->formats;for(unsigned ch=0;ch<buffers->mNumberBuffers;++ch)if(buffers->mBuffers[ch].mData)std::memset(buffers->mBuffers[ch].mData,0,buffers->mBuffers[ch].mDataByteSize);
    }
    const auto at=mach_absolute_time();
    const auto evidence=c->clock.observe(1,c->ns(r.begin),c->ns(at),r.flags&kAudioTimeStampHostTimeValid,c->ns(r.host),r.flags&kAudioTimeStampSampleTimeValid,r.sample,n,Context::rate);
    c->sampleErrors+=evidence.sampleError;c->hostErrors+=evidence.cadenceError||evidence.hostBackwards||evidence.offsetOutlier;
    c->invalidHost+=evidence.hostMissing;c->invalidSample+=!(r.flags&kAudioTimeStampSampleTimeValid);c->halWindow+=evidence.halWindowMiss;
    r.end=mach_absolute_time();c->deadlines+=c->ns(r.end)-c->ns(r.begin)>n*1e9/Context::rate;
    if(c->calls<c->rows.size())c->rows[c->calls]=r;else ++c->dropped;++c->calls;
    *silent=r.received==0;inCallback=false;c->inRender.fetch_sub(1);return noErr;
}
OSStatus outputNotify(void* raw,AudioUnitRenderActionFlags* action,const AudioTimeStamp* stamp,UInt32,UInt32 n,AudioBufferList*)noexcept{
    inCallback=true;auto* c=static_cast<Context*>(raw);c->inRender.fetch_add(1);const auto i=c->notifyCalls++;
    if(i<c->notify.size())c->notify[i]={mach_absolute_time(),stamp?stamp->mHostTime:0,stamp?stamp->mSampleTime:0,stamp?stamp->mRateScalar:0,n,stamp?stamp->mFlags:0,action?*action:0};
    inCallback=false;c->inRender.fetch_sub(1);return noErr;
}
unsigned property(AudioObjectID object,AudioObjectPropertySelector selector){UInt32 value=0,size=sizeof(value);AudioObjectPropertyAddress a{selector,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(object,&a,0,nullptr,&size,&value)!=noErr)throw std::runtime_error("Audio property unavailable");return value;}
}

int main(int argc,char** argv){const auto processEntry=mach_absolute_time();@autoreleasepool{try{
    if(argc<5)throw std::invalid_argument("direct|fifo candidate|baseline seconds output [notify]");
    const std::string mode=argv[1],preset=argv[2];const double seconds=std::stod(argv[3]);const std::filesystem::path out=argv[4];
    if((mode!="direct"&&mode!="fifo")||(preset!="candidate"&&preset!="baseline")||seconds<.1||seconds>100||std::filesystem::exists(out))throw std::invalid_argument("Bounded fresh experiment required");
    std::filesystem::create_directories(out);Context c;mach_timebase_info_data_t tb{};mach_timebase_info(&tb);c.numer=tb.numer;c.denom=tb.denom;
    std::vector<std::pair<const char*,std::uint64_t>> marks;marks.reserve(20);marks.emplace_back("process_entry",processEntry);
    auto mark=[&](const char* name){marks.emplace_back(name,mach_absolute_time());};
    c.total=std::size_t(std::llround(seconds*Context::rate));c.rows.resize(std::size_t(seconds*400)+2048);touch(c.rows);
    if(argc>5){c.notify.resize(c.rows.size()*4);touch(c.notify);}
    for(unsigned ch=0;ch<2;++ch){c.pcm[ch].resize(c.total);for(std::size_t i=0;i<c.total;++i){const auto tag=std::uint32_t(i*1664525u+ch*1013904223u);c.pcm[ch][i]=float(.05*std::sin(i*(ch?451.:337.)*6.283185307179586/Context::rate))+float(int(tag&65535)-32768)*0x1p-22f;}}
    mark("pcm_prepared");
    std::atomic<bool> stop{false},ready{mode=="direct"};std::thread worker;std::vector<WriteRow> writes;
    if(mode=="fifo"){c.fifo=std::make_unique<ts::Phase14AudioFifo>(2,16384);writes.resize(c.total/2048+32);touch(writes);}
    std::size_t writeCount=0;std::uint64_t workerId=0;
    if(c.fifo)worker=std::thread([&]{pthread_setname_np("Fix2 PCM feeder");pthread_threadid_np(nullptr,&workerId);std::size_t pos=0;const auto lead=preset=="candidate"?16384u:12288u;
        while(!stop.load(std::memory_order_acquire)&&pos<c.total){const auto count=std::min<std::size_t>(2048,c.total-pos);if(c.fifo->free()<count||c.fifo->available()>=lead){ready=true;std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
            WriteRow r;r.begin=mach_absolute_time();r.thread=workerId;r.first=pos;r.count=count;r.before=c.fifo->writePosition();const float* p[]={c.pcm[0].data()+pos,c.pcm[1].data()+pos};if(!c.fifo->write(p,count))break;pos+=count;r.after=c.fifo->writePosition();r.end=mach_absolute_time();if(writeCount<writes.size())writes[writeCount++]=r;
            if(c.fifo->available()>=lead||pos==c.total)ready=true;
        }});
    struct WorkerGuard{std::atomic<bool>& stop;std::thread& thread;~WorkerGuard(){stop=true;if(thread.joinable())thread.join();}} guard{stop,worker};
    mark("engine_construct_request");AVAudioEngine* engine=[[AVAudioEngine alloc]init];mark("engine_construct_return");
    const unsigned device=property(kAudioObjectSystemObject,kAudioHardwarePropertyDefaultOutputDevice);auto actual=[engine.outputNode outputFormatForBus:0];
    const auto deviceRate=actual.sampleRate;const auto channels=actual.channelCount;const auto buffer=property(device,kAudioDevicePropertyBufferFrameSize);
    auto format=[[AVAudioFormat alloc]initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:Context::rate channels:2 interleaved:NO];
    Context* ctx=&c;mark("source_construct_request");AVAudioSourceNode* source=[[AVAudioSourceNode alloc]initWithFormat:format renderBlock:^OSStatus(BOOL* s,const AudioTimeStamp* t,AVAudioFrameCount n,AudioBufferList* b){return render(ctx,s,t,n,b);}];mark("source_construct_return");
    [engine attachNode:source];[engine connect:source to:engine.mainMixerNode format:format];engine.mainMixerNode.outputVolume=.5f;mark("nodes_connected");
    mark("prepare_request");[engine prepare];mark("prepare_return");
    const auto waitBegin=std::chrono::steady_clock::now();while(!ready){if(std::chrono::steady_clock::now()-waitBegin>std::chrono::seconds(5))throw std::runtime_error("PCM feeder not ready");std::this_thread::sleep_for(std::chrono::microseconds(100));}mark("worker_ready");
    AudioUnit outputUnit=nullptr;if(!c.notify.empty()){outputUnit=engine.outputNode.audioUnit;if(AudioUnitAddRenderNotify(outputUnit,outputNotify,&c)!=noErr)throw std::runtime_error("Render notification unavailable");}
    NSError* error=nil;mark("start_request");if(![engine startAndReturnError:&error])throw std::runtime_error(error?[[error description]UTF8String]:"Audio start failed");mark("start_return");
    const auto started=std::chrono::steady_clock::now();bool timeout=false;
    while(c.consumed.load(std::memory_order_acquire)<c.total){if(std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()>seconds+10){timeout=true;break;}std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    std::this_thread::sleep_for(std::chrono::milliseconds(30));mark("engine_stop_request");[engine stop];mark("engine_stopped");
    if(outputUnit)AudioUnitRemoveRenderNotify(outputUnit,outputNotify,&c);
    while(c.inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));
    [engine detachNode:source];stop=true;if(worker.joinable())worker.join();mark("worker_joined");
    // Identifier reconstructed after join from the already recorded control
    // milestones. No Objective-C engine state query is made in render().
    const auto stateAt=[&](std::uint64_t ticks){unsigned state=0;for(auto [name,at]:marks){if(at>ticks)continue;
        if(!std::strcmp(name,"prepare_return"))state=1;else if(!std::strcmp(name,"start_request"))state=2;
        else if(!std::strcmp(name,"start_return"))state=3;else if(!std::strcmp(name,"engine_stop_request"))state=4;
        else if(!std::strcmp(name,"engine_stopped"))state=5;}return state;};
    std::ofstream rows(out/"callbacks.csv");rows<<"sequence,session,epoch,begin_ticks,end_ticks,host_ticks,sample_time,rate_scalar,flags,requested,received,logical_before,read_before,read_after,write_before,write_after,fifo_before,fifo_after,thread,format_id,engine_state_id\n"<<std::setprecision(17);
    for(std::size_t i=0;i<std::min(c.calls,c.rows.size());++i){const auto& r=c.rows[i];rows<<i+1<<",1,1,"<<r.begin<<','<<r.end<<','<<r.host<<','<<r.sample<<','<<r.scalar<<','<<r.flags<<','<<r.frames<<','<<r.received<<','<<r.logical<<','<<r.readBefore<<','<<r.readAfter<<','<<r.writeBefore<<','<<r.writeAfter<<','<<r.fifoBefore<<','<<r.fifoAfter<<','<<r.thread<<",1,"<<stateAt(r.begin)<<'\n';}
    std::ofstream writer(out/"writes.csv");writer<<"begin_ticks,end_ticks,thread,logical_first,count,write_before,write_after\n";for(std::size_t i=0;i<writeCount;++i){const auto& r=writes[i];writer<<r.begin<<','<<r.end<<','<<r.thread<<','<<r.first<<','<<r.count<<','<<r.before<<','<<r.after<<'\n';}
    std::ofstream notify(out/"output_notify.csv");notify<<"sequence,ticks,host_ticks,sample_time,rate_scalar,frames,flags,action\n"<<std::setprecision(17);for(std::size_t i=0;i<std::min(c.notifyCalls,c.notify.size());++i){const auto& r=c.notify[i];notify<<i+1<<','<<r.ticks<<','<<r.host<<','<<r.sample<<','<<r.scalar<<','<<r.frames<<','<<r.flags<<','<<r.action<<'\n';}
    std::ofstream startup(out/"startup.csv");startup<<"stage,ticks\n";for(auto [name,ticks]:marks)startup<<name<<','<<ticks<<'\n';
    std::ofstream pcm(out/"prepared.f32",std::ios::binary);for(std::size_t i=0;i<c.total;++i)for(unsigned ch=0;ch<2;++ch)pcm.write(reinterpret_cast<const char*>(&c.pcm[ch][i]),sizeof(float));
    const bool pass=!timeout&&c.position==c.total&&!c.missing&&!c.mismatch&&!c.formats&&!c.dropped&&!c.sampleErrors&&!c.hostErrors&&!c.invalidHost&&!c.invalidSample&&!c.deadlines&&!c.halWindow&&!callbackNew&&(!c.fifo||!c.fifo->rejectedWrites());
    std::ofstream result(out/"summary.json");result<<std::boolalpha<<std::setprecision(17)<<"{\n\"PASS\":"<<pass<<",\"mode\":\""<<mode<<"\",\"preset\":\""<<preset<<"\",\"pid\":"<<getpid()<<",\"device\":"<<device<<",\"device_rate\":"<<deviceRate<<",\"device_channels\":"<<channels<<",\"device_buffer\":"<<buffer<<",\"source_rate\":48000,\"source_channels\":2,\"gain\":0.5,\"format_id\":1,\"engine_state_mapping\":\"0 setup;1 prepared;2 starting;3 running;4 stopping;5 stopped\",\"device_configuration_changes_measured\":false,\"timebase_numer\":"<<c.numer<<",\"timebase_denom\":"<<c.denom<<",\"frames\":"<<c.total<<",\"consumed\":"<<c.position<<",\"calls\":"<<c.calls<<",\"missing_frames\":"<<c.missing<<",\"pcm_mismatches\":"<<c.mismatch<<",\"sample_errors\":"<<c.sampleErrors<<",\"host_errors\":"<<c.hostErrors<<",\"invalid_host\":"<<c.invalidHost<<",\"invalid_sample\":"<<c.invalidSample<<",\"callback_deadlines\":"<<c.deadlines<<",\"hal_window_misses\":"<<c.halWindow<<",\"format_errors\":"<<c.formats<<",\"dropped\":"<<c.dropped<<",\"callback_cpp_new\":"<<callbackNew.load()<<",\"worker_thread\":"<<workerId<<",\"rejected_writes\":"<<(c.fifo?c.fifo->rejectedWrites():0)<<",\"notify_calls\":"<<c.notifyCalls<<",\"notify_dropped\":"<<(c.notifyCalls>c.notify.size()?c.notifyCalls-c.notify.size():0)<<",\"timeout\":"<<timeout<<",\"physical_audio_continuity_verified\":false,\"workgroup_applicable\":false}\n";
    std::cout<<(pass?"PASS":"FAIL")<<" sample_errors="<<c.sampleErrors<<" host_errors="<<c.hostErrors<<" missing="<<c.missing<<'\n';return pass?0:2;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}}
