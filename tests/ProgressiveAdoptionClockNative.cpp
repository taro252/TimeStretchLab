// Dedicated normal-thread startup profile. No loop/seek/route operation is sent.
// Link phase61_callback_heap_probe. External fixed RAW is supplied by the caller;
// this host never synthesizes its own reference and never changes PCM or gain.
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase58Diagnostics.h"
#include "prototype/Phase58FixAllocationProbe.h"
#include "audio/WavStream.h"
#include "Phase61CallbackMallocProbe.h"
#include "Phase62FixTrace.h"
#include <mach/mach_time.h>
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <new>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

// Same explicit executable-only probe as the existing Phase61 native hosts.
namespace {
thread_local bool adoptionCallbackCounting=false;
thread_local std::uint64_t adoptionCallbackNew=0;
void noteAdoptionNew(){ts::prototype::phase58::noteDspAllocation();if(adoptionCallbackCounting)++adoptionCallbackNew;}
}
void* operator new(std::size_t n){noteAdoptionNew();if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){noteAdoptionNew();void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
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
using namespace ts::playback;
using State=progressive::State;
using Clock=std::chrono::steady_clock;
namespace fs=std::filesystem;
void need(bool value,const std::string& why){if(!value)throw std::runtime_error(why);}
std::string q(const std::string& value){return ts::prototype::phase58::jsonString(value);}
std::uint64_t steadyNs(){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();}
void finiteNumber(std::ostream& out,double value){if(std::isfinite(value))out<<value;else out<<"null";}
std::string hashFile(const fs::path& path){
    std::ifstream in(path,std::ios::binary);need(bool(in),"Cannot hash: "+path.string());
    ts::prototype::Phase45PcmDigest digest;std::array<char,65536> bytes{};
    while(in.read(bytes.data(),bytes.size())||in.gcount())digest.update(bytes.data(),std::size_t(in.gcount()));
    need(in.eof(),"Incomplete hash read");return digest.finish();
}
std::string hashPcm(const std::vector<float>& pcm,std::size_t samples){
    ts::prototype::Phase45PcmDigest digest;digest.update(pcm.data(),samples*sizeof(float));return digest.finish();
}
std::uint16_t u16(const unsigned char* b){return std::uint16_t(b[0])|(std::uint16_t(b[1])<<8);}
std::uint32_t u32(const unsigned char* b){return std::uint32_t(u16(b))|(std::uint32_t(u16(b+2))<<16);}
struct WavInfo {std::uint32_t rate=0;std::size_t channels=0,frames=0;};
WavInfo inspect(const fs::path& path){
    std::ifstream in(path,std::ios::binary);std::array<unsigned char,12> head{};
    need(bool(in.read(reinterpret_cast<char*>(head.data()),head.size())),"WAV header");
    need(std::string(reinterpret_cast<char*>(head.data()),4)=="RIFF"&&std::string(reinterpret_cast<char*>(head.data()+8),4)=="WAVE","RIFF/WAVE required");
    WavInfo info;bool fmt=false,data=false;std::uint32_t dataBytes=0,align=0;
    for(;;){std::array<unsigned char,8> h{};in.read(reinterpret_cast<char*>(h.data()),h.size());if(in.gcount()==0)break;need(in.gcount()==8,"WAV chunk header");
        const auto size=u32(h.data()+4);const auto start=in.tellg();need(start>=0&&std::uint64_t(start)+size<=fs::file_size(path),"WAV chunk bounds");
        const std::string kind(reinterpret_cast<char*>(h.data()),4);
        if(kind=="fmt "){std::array<unsigned char,16> f{};need(!fmt&&size>=f.size()&&bool(in.read(reinterpret_cast<char*>(f.data()),f.size())),"WAV fmt");
            need(u16(f.data())==3&&u16(f.data()+14)==32,"Float32 WAV required");info.channels=u16(f.data()+2);info.rate=u32(f.data()+4);align=u16(f.data()+12);need(align==info.channels*sizeof(float),"WAV block alignment");fmt=true;
        }else if(kind=="data"){need(!data,"Multiple data chunks");dataBytes=size;data=true;}
        in.seekg(start+std::streamoff(size)+std::streamoff(size%2));need(bool(in),"WAV chunk seek");
    }
    need(fmt&&data&&align&&dataBytes%align==0,"WAV data layout");info.frames=dataBytes/align;return info;
}
struct Args {fs::path input,output,candidateReference,baselineReference;std::uint32_t speed=0,rate=0;unsigned repeats=10;};
std::uint32_t unsignedOption(const std::string& value){
    need(!value.empty()&&std::all_of(value.begin(),value.end(),[](unsigned char c){return c>='0'&&c<='9';}),"Unsigned decimal option required");
    std::size_t used=0;const auto n=std::stoull(value,&used);need(used==value.size()&&n<=std::numeric_limits<std::uint32_t>::max(),"Option range");return std::uint32_t(n);
}
Args parse(int argc,char** argv){
    need(argc>=3,"INPUT OUTPUT --speed 400000|500000|2000000 --rate 48000 --candidate-reference FULL_RAW --baseline-reference FULL_RAW [--repeats 10]");
    Args a;a.input=fs::absolute(argv[1]);a.output=fs::absolute(argv[2]);std::set<std::string> seen;
    for(int i=3;i<argc;i+=2){need(i+1<argc,"Missing option value");const std::string key=argv[i],value=argv[i+1];need(seen.insert(key).second,"Duplicate option");
        if(key=="--speed")a.speed=unsignedOption(value);else if(key=="--rate")a.rate=unsignedOption(value);
        else if(key=="--repeats")a.repeats=unsignedOption(value);else if(key=="--candidate-reference")a.candidateReference=fs::absolute(value);
        else if(key=="--baseline-reference")a.baselineReference=fs::absolute(value);else throw std::invalid_argument("Unknown option: "+key);
    }
    need(a.speed==400000||a.speed==500000||a.speed==2000000,"Only separate 0.40/0.50/2.00 speed profiles are allowed");
    need(a.rate==48000,"Explicit --rate 48000 required for this mono/stereo Float32 profile");
    need(a.repeats>0&&a.repeats<=100,"Repeat range 1..100");need(!a.candidateReference.empty()&&!a.baselineReference.empty(),"Both independent preset references required");return a;
}
struct Reference {fs::path path;std::string sha;std::size_t frames=0;std::vector<float> prefix;};
Reference loadReference(const fs::path& path,std::size_t frames,std::size_t channels,std::size_t prefixFrames){
    need(fs::is_regular_file(path)&&fs::file_size(path)==frames*channels*sizeof(float),"Independent full RAW length mismatch: "+path.string());
    Reference r;r.path=path;r.frames=frames;r.sha=hashFile(path);r.prefix.resize(prefixFrames*channels);
    std::ifstream in(path,std::ios::binary);need(bool(in.read(reinterpret_cast<char*>(r.prefix.data()),r.prefix.size()*sizeof(float))),"Reference prefix read");
    need(std::all_of(r.prefix.begin(),r.prefix.end(),[](float x){return std::isfinite(x);}),"Reference prefix has nonfinite samples");return r;
}
struct RawRecord {std::size_t capturedAt=0,frames=0,outputAt=0;std::uint64_t generation=0,epoch=0,session=0;};
struct Capture {
    std::size_t channels=0,used=0,count=0,errors=0,overflowFrames=0;
    std::vector<float> pcm;std::vector<RawRecord> records;
    Capture(std::size_t ch,std::size_t frames):channels(ch),pcm(ch*frames,0.f),records(2048){
        // Ordinary thread writes all pages before prepare/play.
        std::fill(pcm.begin(),pcm.end(),0.f);std::fill(records.begin(),records.end(),RawRecord{});
    }
    static void observe(void* context,const float*const* p,std::size_t n,std::size_t at,
        std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& x=*static_cast<Capture*>(context);if(!n)return;
        if(!p||countInvalid(x,n)){++x.errors;x.overflowFrames+=n;return;}
        for(std::size_t c=0;c<x.channels;++c)if(!p[c]){++x.errors;return;}
        x.records[x.count++]={x.used,n,at,generation,epoch,session};
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<x.channels;++c)x.pcm[(x.used+i)*x.channels+c]=p[c][i];x.used+=n;
    }
    static bool countInvalid(const Capture& x,std::size_t n)noexcept{return x.count==x.records.size()||n>x.pcm.size()/x.channels-x.used;}
};
struct Mark {const char* name;std::uint64_t before=0,mach=0,after=0;};
void mark(std::vector<Mark>& marks,const char* name){const auto before=steadyNs(),ticks=mach_absolute_time(),after=steadyNs();marks.push_back({name,before,ticks,after});}
void ready(ProgressiveMacPlaybackEngine& e){const auto deadline=Clock::now()+std::chrono::seconds(120);while(e.getPlaybackState()!=State::Ready){
    const auto s=e.getStateSnapshot();need(s.state!=State::Failed,s.error);need(Clock::now()<deadline,"Ready timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
void regularCsv(const fs::path& path,const std::vector<MacCallbackRecord>& rows){
    std::ofstream out(path);need(bool(out),"callbacks CSV open");out<<std::setprecision(17);
    out<<"sequence,clock_epoch,start_ns,io_end_ns,end_ns,host_ticks,host_ns,sample_time,flags,rate_scalar,requested,wanted,received,output_before,fifo_before,session,generation,read_before,read_after,write_before,write_after,raw_fields_present\n";
    for(const auto& r:rows){out<<r.sequence<<','<<r.epoch<<','<<r.startNs<<','<<r.ioEndNs<<','<<r.endNs<<','<<r.hostTicks<<','<<r.hostNs<<',';finiteNumber(out,r.sampleTime);out<<','<<r.timestampFlags<<',';finiteNumber(out,r.rateScalar);
        out<<','<<r.requested<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.fifoBefore<<','<<r.raw.session<<','<<r.raw.generation<<','<<r.raw.fifoReadBefore<<','<<r.raw.fifoReadAfter<<','<<r.raw.fifoWriteBefore<<','<<r.raw.fifoWriteAfter<<','<<(r.raw.wanted||r.raw.received)<<'\n';}
    need(bool(out),"callbacks CSV write");
}
struct CaseResult {bool pass=false,functional=false,pcm=false,clock=false,realtime=false,complete=false;
    std::uint64_t host=0,sample=0,hal=0,worker=0,callback=0,cppNew=0,workerNew=0,heap=0,frees=0,padding=0,missing=0;bool cppMeasured=false,workerMeasured=false;std::string json;};
CaseResult one(const Args& a,const WavInfo& info,const Reference& ref,Preset preset,unsigned repeat,const std::string& inputSha,mach_timebase_info_data_t tb){
    const std::string name=(preset==Preset::Candidate?"candidate_":"baseline_")+std::to_string(a.speed)+"_"+std::to_string(repeat);
    const auto out=a.output/name;need(fs::create_directory(out),"Existing case directory");
    Capture capture(info.channels,a.rate);std::vector<Mark> marks;marks.reserve(16);
    std::vector<MacCallbackRecord> callbacks;std::vector<ProgressiveCallbackRecord> traces,anomaly;
    ProgressiveDiagnostics paused,final;ProgressiveNativeDiagnostics native;ProgressiveStateSnapshot initial;
    bool pausedOK=false,stoppedOK=false,loopOff=false,readyAnalysis=false;std::string error;
    ProgressiveMacPlaybackEngine engine;ProgressiveOptions options;options.initialSpeed=double(a.speed)/1e6;options.preset=preset;
    options.allowExperimentalLoops=true; // bounded existing trace storage only; no loop request
    options.callbackRecordLimit=2048;options.observerContext=&capture;options.observeEpochPcm=Capture::observe;
    phase61_heap_reset();options.allocationHooks={[]()noexcept{adoptionCallbackNew=0;adoptionCallbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();adoptionCallbackCounting=false;},[]()noexcept{return adoptionCallbackNew;}};
    try{
        mark(marks,"prepare_request");engine.prepare(a.input,options);ready(engine);mark(marks,"ready_observed");
        initial=engine.getStateSnapshot();readyAnalysis=engine.getPlaybackDiagnostics().pipeline.analysisDone;
        mark(marks,"play_request");need(engine.play(),"play rejected");mark(marks,"play_return");
        std::this_thread::sleep_for(std::chrono::milliseconds(250));mark(marks,"pause_request");
        need(engine.pause(),"pause rejected");pausedOK=engine.getPlaybackState()==State::Paused;need(pausedOK,"Pause did not quiesce");mark(marks,"pause_return");
        paused=engine.getPlaybackDiagnostics();native=engine.getNativeDiagnostics();
        callbacks=engine.callbackRecords();traces=engine.loopCallbackRecords();anomaly=engine.loopClockAnomalyRecords();
        const auto loop=engine.getLoopSnapshot();loopOff=!loop.enabled&&!loop.cycles;
    }catch(const std::exception& ex){error=ex.what();}
    try{mark(marks,"stop_request");engine.stop();mark(marks,"stop_return");stoppedOK=engine.getPlaybackState()==State::Stopped;final=engine.getPlaybackDiagnostics();
        if(!pausedOK){native=engine.getNativeDiagnostics();callbacks=engine.callbackRecords();traces=engine.loopCallbackRecords();anomaly=engine.loopClockAnomalyRecords();}
    }catch(const std::exception& ex){if(!error.empty())error+="; ";error+=ex.what();}
    // The callback is now quiescent and workers joined. All formatting/hashing is here.
    regularCsv(out/"callbacks.csv",callbacks);writePhase62Trace(out/"callbacks_all_spans.jsonl",traces);writePhase62Trace(out/"clock_anomaly_window.jsonl",anomaly);
    std::ofstream raw(out/"raw_before_gain.f32",std::ios::binary);raw.write(reinterpret_cast<const char*>(capture.pcm.data()),capture.used*info.channels*sizeof(float));need(bool(raw),"RAW write");raw.close();
    std::ofstream records(out/"raw_records.jsonl");for(std::size_t i=0;i<capture.count;++i){const auto& r=capture.records[i];records<<"{\"captured_at\":"<<r.capturedAt<<",\"frames\":"<<r.frames<<",\"output_at\":"<<r.outputAt<<",\"generation\":"<<r.generation<<",\"epoch\":"<<r.epoch<<",\"session\":"<<r.session<<"}\n";}need(bool(records),"RAW records write");
    std::ofstream control(out/"control_marks.csv");control<<"event,steady_before_ns,mach_ticks,steady_after_ns\n";for(const auto& m:marks)control<<m.name<<','<<m.before<<','<<m.mach<<','<<m.after<<'\n';need(bool(control),"Control marks write");
    std::size_t offset=0,metadataErrors=0,nonfinite=0,bitErrors=0;std::uint64_t generation=0,epoch=0,session=0;
    for(std::size_t i=0;i<capture.count;++i){const auto& r=capture.records[i];
        if(i==0){generation=r.generation;epoch=r.epoch;session=r.session;}
        if(r.capturedAt!=offset||r.outputAt!=offset||r.generation!=generation||r.epoch!=epoch||r.session!=session||!generation||!epoch||!session)++metadataErrors;
        offset+=r.frames;
    }
    if(generation!=initial.inputGeneration||session!=initial.session||(initial.renderEpoch&&epoch!=initial.renderEpoch))++metadataErrors;
    for(std::size_t i=0;i<capture.used*info.channels;++i){if(!std::isfinite(capture.pcm[i])||!std::isfinite(ref.prefix[i]))++nonfinite;
        if(std::bit_cast<std::uint32_t>(capture.pcm[i])!=std::bit_cast<std::uint32_t>(ref.prefix[i]))++bitErrors;}
    std::size_t received=0,wanted=0,callbackOffset=0,callbackErrors=0,spanPadding=0,spanAffected=0,spanMissing=0,pauseSilence=0,traceErrors=0;
    ts::prototype::Phase46HostClock independentClock;std::uint64_t recomputedHost=0,recomputedSample=0,recomputedHal=0,invalidSample=0,invalidScalar=0;
    std::ofstream clocks(out/"clock_recomputed.jsonl");clocks<<std::setprecision(17)<<std::boolalpha;
    for(std::size_t i=0;i<callbacks.size();++i){const auto& c=callbacks[i];
        if(c.sequence!=i+1||!c.epoch||!c.requested||c.endNs<c.ioEndNs||c.ioEndNs<c.startNs||c.raw.received>c.raw.wanted)++callbackErrors;
        if(c.raw.received){if(c.raw.outputBefore!=callbackOffset)++callbackErrors;callbackOffset+=c.raw.received;}
        received+=c.raw.received;wanted+=c.raw.wanted;
        const auto e=independentClock.observe(c.epoch,c.startNs,c.ioEndNs,(c.timestampFlags&2)!=0,c.hostNs,(c.timestampFlags&1)!=0,c.sampleTime,c.requested,info.rate);
        recomputedHost+=std::uint64_t(e.hostMissing)+std::uint64_t(e.hostBackwards)+std::uint64_t(e.cadenceError||e.offsetOutlier);recomputedSample+=e.sampleError;
        recomputedHal+=c.hostNs&&c.endNs>c.hostNs+std::max(100000.,2e9/info.rate);
        invalidSample+=!(c.timestampFlags&1)||!std::isfinite(c.sampleTime);invalidScalar+=!(c.timestampFlags&4)||!std::isfinite(c.rateScalar);
        clocks<<"{\"sequence\":"<<c.sequence<<",\"first\":"<<e.first<<",\"host_error\":"<<(e.hostMissing||e.hostBackwards||e.cadenceError||e.offsetOutlier)<<",\"sample_error\":"<<e.sampleError<<",\"host_delta_ns\":"<<e.hostDeltaNs<<",\"host_progress_error_ns\":"<<e.hostProgressErrorNs<<",\"sample_delta\":";finiteNumber(clocks,e.sampleDelta);clocks<<",\"sample_progress_error\":";finiteNumber(clocks,e.sampleProgressError);clocks<<"}\n";
    }
    need(bool(clocks),"Clock recomputation write");
    for(std::size_t i=0;i<traces.size();++i){const auto& r=traces[i];if(r.callback.sequence!=i+1||r.spanCount>r.spans.size()||r.machNumer!=tb.numer||r.machDenom!=tb.denom||r.sourceRate!=info.rate||r.deviceRate!=native.deviceRate)++traceErrors;
        spanPadding+=r.failurePaddingFrames;spanAffected+=r.outputAffectedFrames;spanMissing+=r.oldMissingFrames+r.newMissingFrames;pauseSilence+=r.pauseSilenceFrames;}
    const bool recordComplete=callbacks.size()==native.callbackCalls&&traces.size()==native.callbackCalls&&native.callbackCalls>=3&&!native.callbackRecordsDropped&&!callbackErrors&&!traceErrors;
    const bool lengthOK=capture.used>=a.rate/10&&capture.used<=a.rate&&offset==capture.used&&received==capture.used&&received==final.consumedFrames&&wanted==received;
    const auto& policy=final.pipeline.scheduling;
    const bool joined=final.pipeline.finalDataAvailable&&stoppedOK&&!policy.active&&policy.promotions>0&&policy.promotions==policy.joins&&policy.joins==policy.leaves&&policy.leaves==policy.restores&&policy.intervalStarts==policy.intervalFinishes;
    const bool policyOK=policy.enabled&&policy.policyMeasured&&policy.observedPolicy==2&&!policy.policyErrors&&!policy.joinErrors&&!policy.restoreErrors&&!policy.intervalErrors&&!policy.queryErrors&&!policy.waitErrors&&!policy.wakeErrors;
    const auto hostErrors=native.hostMissing+native.hostBackwards+native.hostCadenceErrors;
    const bool clockAgreement=recomputedHost==hostErrors&&recomputedSample==native.sampleErrors&&recomputedHal==native.halWindowMisses&&invalidSample==native.invalidSampleTimeCalls&&invalidScalar==native.invalidRateScalarCalls;
    const auto heap=phase61_heap_allocations(),frees=phase61_heap_frees();
    const bool allocations=final.callbackCppNew.has_value()&&!*final.callbackCppNew&&!heap&&!frees&&final.pipeline.realtimeAllocationsMeasured&&!final.workerNewCalls;
    const bool deviceValid=native.deviceId&&std::isfinite(native.deviceRate)&&native.deviceRate==info.rate&&native.deviceChannels>=info.channels&&native.deviceBufferFrames;
    CaseResult result;result.complete=pausedOK&&joined&&recordComplete&&error.empty();
    result.pcm=lengthOK&&!capture.errors&&!capture.overflowFrames&&!metadataErrors&&!nonfinite&&!bitErrors;
    result.functional=result.complete&&loopOff&&deviceValid&&final.pipeline.inputSha256==inputSha&&result.pcm&&!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&!spanPadding&&!spanAffected&&!spanMissing&&!final.workgroupErrors;
    result.clock=recordComplete&&clockAgreement&&!hostErrors&&!native.sampleErrors&&!native.halWindowMisses&&!invalidSample&&!invalidScalar&&!native.routeChanges;
    result.realtime=joined&&policyOK&&allocations&&!native.deadlineMisses&&!native.formatErrors&&!final.workerDeadlineMisses;
    result.pass=result.functional&&result.clock&&result.realtime;result.host=hostErrors;result.sample=native.sampleErrors;result.hal=native.halWindowMisses;result.worker=final.workerDeadlineMisses;result.callback=native.deadlineMisses;result.cppNew=final.callbackCppNew.value_or(0);result.cppMeasured=final.callbackCppNew.has_value();result.workerNew=final.workerNewCalls;result.workerMeasured=final.pipeline.realtimeAllocationsMeasured;result.heap=heap;result.frees=frees;result.padding=spanPadding;result.missing=final.missingFrames;
    std::ostringstream row;row<<std::boolalpha<<std::setprecision(17);
    row<<"{\"id\":"<<q(name)<<",\"PASS\":"<<result.pass<<",\"execution_complete\":"<<result.complete<<",\"functional_pass\":"<<result.functional<<",\"raw_prefix_exact\":"<<result.pcm<<",\"clock_pass\":"<<result.clock<<",\"realtime_pass\":"<<result.realtime<<",\"preset\":"<<q(preset==Preset::Candidate?"candidate":"baseline")<<",\"speed_micros\":"<<a.speed<<",\"repeat\":"<<repeat<<",\"error\":"<<q(error)
       <<",\"source_rate\":"<<info.rate<<",\"channels\":"<<info.channels<<",\"input_frames\":"<<info.frames<<",\"input_sha256\":"<<q(inputSha)<<",\"pipeline_input_sha256\":"<<q(final.pipeline.inputSha256)<<",\"reference_path\":"<<q(ref.path.string())<<",\"reference_sha256\":"<<q(ref.sha)<<",\"reference_frames\":"<<ref.frames
       <<",\"captured_frames\":"<<capture.used<<",\"capture_capacity_frames\":"<<a.rate<<",\"capture_errors\":"<<capture.errors<<",\"capture_overflow_frames\":"<<capture.overflowFrames<<",\"metadata_errors\":"<<metadataErrors<<",\"nonfinite_samples\":"<<nonfinite<<",\"different_samples\":"<<bitErrors<<",\"length_pass\":"<<lengthOK<<",\"captured_sha256\":"<<q(hashPcm(capture.pcm,capture.used*info.channels))<<",\"reference_prefix_sha256\":"<<q(hashPcm(ref.prefix,capture.used*info.channels))
       <<",\"callback_records\":"<<callbacks.size()<<",\"trace_records\":"<<traces.size()<<",\"anomaly_records\":"<<anomaly.size()<<",\"record_coverage_pass\":"<<recordComplete<<",\"callback_record_errors\":"<<callbackErrors<<",\"trace_errors\":"<<traceErrors<<",\"callback_calls\":"<<native.callbackCalls<<",\"callback_records_dropped\":"<<native.callbackRecordsDropped<<",\"callback_received_frames\":"<<received<<",\"callback_wanted_frames\":"<<wanted
       <<",\"host_errors\":"<<hostErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_window_misses\":"<<native.halWindowMisses<<",\"invalid_sample_time_calls\":"<<invalidSample<<",\"invalid_rate_scalar_calls\":"<<invalidScalar<<",\"clock_counter_agreement\":"<<clockAgreement<<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"worker_new\":"<<(final.pipeline.realtimeAllocationsMeasured?std::to_string(final.workerNewCalls):"null")
       <<",\"callback_cpp_new_measured\":"<<result.cppMeasured<<",\"worker_new_measured\":"<<result.workerMeasured<<",\"callback_cpp_new\":"<<(final.callbackCppNew?std::to_string(*final.callbackCppNew):"null")<<",\"callback_heap_calls\":"<<heap<<",\"callback_heap_frees\":"<<frees<<",\"allocation_zero_pass\":"<<allocations<<",\"missing_frames\":"<<final.missingFrames<<",\"underrun_calls\":"<<final.underrunCalls<<",\"rejected_writes\":"<<final.rejectedWrites<<",\"span_missing_frames\":"<<spanMissing<<",\"affected_frames\":"<<spanAffected<<",\"failure_padding_frames\":"<<spanPadding<<",\"pause_silence_frames\":"<<pauseSilence
       <<",\"device_values_valid\":"<<deviceValid<<",\"device_id\":"<<native.deviceId<<",\"device_rate\":";finiteNumber(row,native.deviceRate);row<<",\"device_channels\":"<<native.deviceChannels<<",\"device_buffer_frames\":"<<native.deviceBufferFrames<<",\"route_changes\":"<<native.routeChanges<<",\"mach_numer\":"<<tb.numer<<",\"mach_denom\":"<<tb.denom
       <<",\"analysis_complete_at_ready\":"<<readyAnalysis<<",\"analysis_complete_after_stop\":"<<final.pipeline.analysisDone<<",\"loop_requested\":false,\"loop_off\":"<<loopOff<<",\"loop_trace_opt_in\":true,\"joined\":"<<joined<<",\"policy_pass\":"<<policyOK<<",\"policy_measured\":"<<policy.policyMeasured<<",\"observed_policy\":"<<(policy.policyMeasured?std::to_string(policy.observedPolicy):"null")<<",\"promotions\":"<<policy.promotions<<",\"joins\":"<<policy.joins<<",\"leaves\":"<<policy.leaves<<",\"restores\":"<<policy.restores<<",\"interval_starts\":"<<policy.intervalStarts<<",\"interval_finishes\":"<<policy.intervalFinishes<<",\"workgroup_errors\":"<<final.workgroupErrors
       <<",\"fifo_cursor_coverage\":\"this MacCallbackRecord path does not populate raw FIFO cursors or raw generation; exported zeros are defaults, not measured cursors\",\"raw_domain\":\"before final gain 0.5; no source PCM modification\",\"os_context\":\"saved by external wrapper\",\"physical_audio_continuity_verified\":null,\"old_failure_resolved\":false}";
    result.json=row.str();std::ofstream saved(out/"summary.json");saved<<result.json<<'\n';need(bool(saved),"Case summary write");return result;
}
int run(int argc,char** argv){
    const auto a=parse(argc,argv);need(std::endian::native==std::endian::little,"Little-endian Float32 profile required");
    const auto info=inspect(a.input);need(info.rate==a.rate&&(info.channels==1||info.channels==2),"Input must match explicit 48kHz mono/stereo Float32 profile");
    ts::WavStreamReader reader(a.input);need(reader.sampleRate()==info.rate&&reader.channels()==info.channels&&reader.frames()==info.frames,"WAV reader/header mismatch");
    const auto fullFrames=std::size_t((std::uint64_t(info.frames)*1000000+a.speed/2)/a.speed);need(fullFrames>=a.rate,"At least one second of fixed output is required");
    const auto candidate=loadReference(a.candidateReference,fullFrames,info.channels,a.rate),baseline=loadReference(a.baselineReference,fullFrames,info.channels,a.rate);
    const auto inputSha=hashFile(a.input);mach_timebase_info_data_t tb{};need(mach_timebase_info(&tb)==KERN_SUCCESS&&tb.numer&&tb.denom,"Mach timebase");
    need(fs::create_directories(a.output),"Refusing existing output directory");
    std::ofstream expected(a.output/"EXPECTED.json");expected<<std::boolalpha<<"{\"schema\":\"adoption-clock-native-v1\",\"expected_count\":"<<2*a.repeats<<",\"repeats_per_preset\":"<<a.repeats<<",\"speed_micros\":"<<a.speed<<",\"source_rate\":"<<info.rate<<",\"channels\":"<<info.channels<<",\"window_ms\":250,\"capture_capacity_frames\":"<<a.rate<<",\"expected_ids\":[";
    bool first=true;for(const auto preset:{"candidate","baseline"})for(unsigned repeat=0;repeat<a.repeats;++repeat){if(!first)expected<<',';first=false;expected<<q(std::string(preset)+"_"+std::to_string(a.speed)+"_"+std::to_string(repeat));}
    expected<<"],\"input\":"<<q(a.input.string())<<",\"input_sha256\":"<<q(inputSha)<<",\"candidate_reference\":"<<q(candidate.path.string())<<",\"candidate_reference_sha256\":"<<q(candidate.sha)<<",\"baseline_reference\":"<<q(baseline.path.string())<<",\"baseline_reference_sha256\":"<<q(baseline.sha)<<",\"reference_provenance\":\"external caller supplies independent frozen full RAW; audited by wrapper\",\"cpp_new_and_c_heap_probe_required\":true,\"initial_callbacks_excluded\":0,\"loop_requested\":false,\"loop_trace_opt_in\":true,\"physical_audio_continuity_verified\":null,\"old_failure_resolved\":false}\n";need(bool(expected),"EXPECTED write");expected.close();
    std::ofstream rows(a.output/"rows.jsonl");need(bool(rows),"rows open");
    std::size_t completed=0,passed=0,functional=0,pcm=0,clocks=0,realtime=0,complete=0,cppMeasured=0,workerMeasured=0;
    std::uint64_t hostErrors=0,sampleErrors=0,hal=0,worker=0,callback=0,cppNew=0,workerNew=0,heap=0,frees=0,padding=0,missing=0;
    for(auto preset:{Preset::Candidate,Preset::Baseline})for(unsigned repeat=0;repeat<a.repeats;++repeat){
        const auto& ref=preset==Preset::Candidate?candidate:baseline;const auto r=one(a,info,ref,preset,repeat,inputSha,tb);
        rows<<r.json<<'\n';rows.flush();need(bool(rows),"rows write");++completed;passed+=r.pass;functional+=r.functional;pcm+=r.pcm;clocks+=r.clock;realtime+=r.realtime;complete+=r.complete;
        hostErrors+=r.host;sampleErrors+=r.sample;hal+=r.hal;worker+=r.worker;callback+=r.callback;cppNew+=r.cppNew;workerNew+=r.workerNew;cppMeasured+=r.cppMeasured;workerMeasured+=r.workerMeasured;heap+=r.heap;frees+=r.frees;padding+=r.padding;missing+=r.missing;
        std::cout<<(preset==Preset::Candidate?"candidate":"baseline")<<" repeat="<<repeat<<" PASS="<<r.pass<<" clock="<<r.clock<<" raw="<<r.pcm<<std::endl;
    }
    const bool all=completed==2*a.repeats&&passed==completed;
    std::ofstream summary(a.output/"SUMMARY.json");summary<<std::boolalpha<<"{\"schema\":\"adoption-clock-native-summary-v1\",\"PASS\":"<<all<<",\"expected\":"<<2*a.repeats<<",\"completed\":"<<completed<<",\"execution_complete\":"<<(complete==2*a.repeats)<<",\"passed\":"<<passed<<",\"functional_passed\":"<<functional<<",\"raw_prefix_exact_passed\":"<<pcm<<",\"clock_passed\":"<<clocks<<",\"realtime_passed\":"<<realtime<<",\"host_errors\":"<<hostErrors<<",\"sample_errors\":"<<sampleErrors<<",\"hal_window_misses\":"<<hal<<",\"worker_deadlines\":"<<worker<<",\"callback_deadlines\":"<<callback<<",\"callback_cpp_new_measured_cases\":"<<cppMeasured<<",\"worker_new_measured_cases\":"<<workerMeasured<<",\"callback_cpp_new\":"<<(cppMeasured==completed?std::to_string(cppNew):"null")<<",\"worker_new_calls\":"<<(workerMeasured==completed?std::to_string(workerNew):"null")<<",\"callback_heap_calls\":"<<heap<<",\"callback_heap_frees\":"<<frees<<",\"missing_frames\":"<<missing<<",\"failure_padding_frames\":"<<padding<<",\"startup_discontinuity_nonreproduced_in_this_profile\":"<<(clocks==completed&&completed==2*a.repeats)<<",\"initial_callbacks_excluded\":0,\"loop_requested\":false,\"physical_audio_continuity_verified\":null,\"old_failure_resolved\":false,\"source_rate\":"<<info.rate<<",\"channels\":"<<info.channels<<",\"scope\":\"new 48kHz mono/stereo Float32 startup profile only; old failure retained; no DAC/loopback claim\"}\n";need(bool(summary),"SUMMARY write");return all?0:2;
}
}
int main(int argc,char** argv){int code=1;std::thread control([&]{try{code=run(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return code;}
