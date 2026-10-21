// Prototype only. Link the public native engine and phase61_callback_heap_probe.
// No product .mm inclusion, RenderState access, handoff write or callback gate.
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase59Diagnostics.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase58FixAllocationProbe.h"
#include "audio/WavStream.h"
#include "Phase61CallbackMallocProbe.h"
#include "ApiOracleCommitAdapter.h"
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <new>
#include <stdexcept>
#include <string>
#include <array>
#include <vector>
#include <thread>

namespace {thread_local bool counting=false;thread_local std::uint64_t allocations=0;
void allocation(){ts::prototype::phase58::noteDspAllocation();if(counting)++allocations;}}
void* operator new(std::size_t n){allocation();if(auto* p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){allocation();void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}
void operator delete(void* p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t)noexcept{std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}

namespace {
using namespace ts::playback;
namespace phase58=ts::prototype::phase58;
namespace phase59=ts::prototype::phase59;
namespace fs=std::filesystem;
using Clock=std::chrono::steady_clock;
void need(bool ok,const std::string& why){if(!ok)throw std::runtime_error(why);}
std::string q(const std::string& s){std::string r="\"";for(unsigned char c:s){if(c=='\"'||c=='\\'){r+='\\';r+=char(c);}else if(c=='\n')r+="\\n";else if(c<32)r+='?';else r+=char(c);}return r+'\"';}
std::string sha(const fs::path& p){std::ifstream f(p,std::ios::binary);need(bool(f),"SHA input absent");ts::prototype::Phase45PcmDigest d;std::array<char,65536> b{};while(f.read(b.data(),b.size())||f.gcount())d.update(b.data(),std::size_t(f.gcount()));need(f.eof(),"SHA input incomplete");return d.finish();}
template<class F> void until(ProgressiveMacPlaybackEngine& e,F f,const char* reason,unsigned seconds=180){const auto end=Clock::now()+std::chrono::seconds(seconds);while(!f()){const auto s=e.getStateSnapshot();need(s.state!=progressive::State::Failed,s.error);need(Clock::now()<end,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
progressive::LoopContext context(ProgressiveMacPlaybackEngine& e){const auto s=e.getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
struct RawRow {std::uint64_t sampleFrame=0,frames=0,outputAt=0,generation=0,epoch=0,session=0;};
struct OutputRow {std::uint64_t sampleFrame=0;ProgressiveOutputSpan span;};
struct Capture {
    std::size_t channels=0,rawCount=0,outputCount=0,rawUsed=0;
    std::vector<float> raw,output;
    std::vector<RawRow> rawRows;
    std::vector<OutputRow> outputRows;
    std::atomic<std::uint64_t> frames{0},errors{0},nonfinite{0},missing{0};
    Capture(unsigned rate,std::size_t ch,unsigned seconds):channels(ch){
        const std::size_t capacity=std::size_t(rate)*seconds;
        const std::size_t budget=(capacity*2+4096)*ch*sizeof(float)+65536*(sizeof(RawRow)+sizeof(OutputRow));
        need(budget<=256ULL*1024*1024,"separate host capture budget exceeds 256MiB");
        raw.resize((capacity+4096)*ch);output.resize(capacity*ch);rawRows.resize(65536);outputRows.resize(65536);
    }
    static void source(void* p,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t gen,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& x=*static_cast<Capture*>(p);if(!n)return;
        if(x.rawCount==x.rawRows.size()||(x.rawUsed+n)*x.channels>x.raw.size()){++x.errors;return;}
        x.rawRows[x.rawCount++]={x.rawUsed,n,at,gen,epoch,session};
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<x.channels;++c){const auto v=pcm[c][i];x.raw[(x.rawUsed+i)*x.channels+c]=v;if(!std::isfinite(v))++x.nonfinite;}
        x.rawUsed+=n;
    }
    static void processed(void* p,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& x=*static_cast<Capture*>(p);const auto at=x.frames.load(std::memory_order_relaxed);
        if(!span.frames||span.callbackFrame!=at||x.outputCount==x.outputRows.size()||(at+span.frames)*x.channels>x.output.size()){++x.errors;return;}
        x.outputRows[x.outputCount++]={at,span};
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<x.channels;++c){const auto v=pcm[c][i];x.output[(at+i)*x.channels+c]=v;if(!std::isfinite(v))++x.nonfinite;}
        x.missing.fetch_add(span.oldMissingFrames+span.newMissingFrames+span.outputAffectedFrames+span.failurePaddingFrames,std::memory_order_relaxed);
        x.frames.store(at+span.frames,std::memory_order_release);
    }
};
void rawFile(const fs::path& p,const std::vector<float>& data,std::size_t frames,std::size_t channels){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(data.data()),frames*channels*sizeof(float));need(bool(f),"capture write failed");}
void exportCapture(const fs::path& out,const Capture& x){
    rawFile(out/"observed_raw.f32",x.raw,x.rawUsed,x.channels);rawFile(out/"observed_processed.f32",x.output,x.frames.load(),x.channels);
    std::ofstream r(out/"raw_chunks.csv");r<<"sample_frame,frames,output_at,input_generation,epoch,session\n";
    for(std::size_t i=0;i<x.rawCount;++i){const auto& v=x.rawRows[i];r<<v.sampleFrame<<','<<v.frames<<','<<v.outputAt<<','<<v.generation<<','<<v.epoch<<','<<v.session<<'\n';}
    std::ofstream f(out/"output_spans.csv");f<<"sample_frame,callback_frame,frames,new_epoch,old_epoch,new_output,old_output,new_received,old_received,mixed,transition_offset,transition_length,periodic,head,tail,period_frames,period_offset,boundary_frames,correction_before_mix,old_periodic,old_head,old_tail,old_period_frames,old_period_offset,old_boundary_frames,old_missing,new_missing,affected,padding\n";
    for(std::size_t i=0;i<x.outputCount;++i){const auto& row=x.outputRows[i];const auto& s=row.span;
        f<<row.sampleFrame<<','<<s.callbackFrame<<','<<s.frames<<','<<s.newEpoch<<','<<s.oldEpoch<<','<<s.newOutputOffset<<','<<s.oldOutputOffset<<','<<s.newReceivedFrames<<','<<s.oldReceivedFrames<<','<<s.mixedFrames<<','<<s.transitionOffset<<','<<s.transitionLength<<','<<s.periodicBoundary<<','<<s.correctionHead<<','<<s.correctionTail<<','<<s.periodFrames<<','<<s.periodOffset<<','<<s.boundaryFrames<<','<<s.correctionBeforeMix<<','<<s.oldPeriodicBoundary<<','<<s.oldCorrectionHead<<','<<s.oldCorrectionTail<<','<<s.oldPeriodFrames<<','<<s.oldPeriodOffset<<','<<s.oldBoundaryFrames<<','<<s.oldMissingFrames<<','<<s.newMissingFrames<<','<<s.outputAffectedFrames<<','<<s.failurePaddingFrames<<'\n';}
}
void exportExternal(const fs::path& out,const std::vector<progressive::LoopSpeedOperation>& ops){
    std::ofstream f(out/"external_requests.json");f<<std::boolalpha<<'[';bool comma=false;
    for(const auto& o:ops){if(comma)f<<',';comma=true;f<<"{\"id\":"<<o.id<<",\"loop_id\":"<<o.loopID<<",\"input_generation\":"<<o.inputGeneration<<",\"source_session\":"<<o.sourceSession<<",\"source_epoch\":"<<o.sourceRenderEpoch<<",\"accepted_cycle\":"<<o.acceptedCycle<<",\"target\":"<<o.speedMicros<<",\"state\":"<<q(progressive::name(o.state))<<",\"preparation_version\":"<<o.preparationVersion<<",\"dynamic_id\":"<<o.dynamicOperationID<<",\"dynamic_session\":"<<o.dynamicSession<<",\"planning_epoch\":"<<o.planningRenderEpoch<<",\"render_epoch\":"<<o.renderEpoch<<",\"producer_cycle\":"<<o.producerCycle<<",\"cycle\":"<<o.cycle<<",\"map_version\":"<<o.mapVersion<<",\"output_end\":"<<o.outputEnd<<",\"first_changed\":"<<o.firstChangedOutputFrame<<",\"completion\":"<<o.completionOutputFrame<<",\"committed\":"<<o.committed<<",\"output_started\":"<<o.outputStarted<<",\"fixed_boundary\":"<<o.fixedBoundary<<",\"reason\":"<<q(o.reason)<<'}';}f<<"]\n";
}
void exportCommit(const fs::path& out,const ApiOracleCommitEvidence& e){
    const auto& d=e.descriptor;std::ofstream f(out/"COMMIT.json");f<<std::boolalpha;
    f<<"{\"descriptor_committed\":"<<(d.state==phase58::LoopTransitionState::Committed)<<",\"atomic_commit_sample\":"<<e.atomicCommitSample<<",\"sequence\":"<<e.sequence<<",\"external_id\":"<<e.externalID<<",\"loop_id\":"<<e.loopID<<",\"input_generation\":"<<e.inputGeneration<<",\"dynamic_session\":"<<e.dynamicSession<<",\"planning_epoch\":"<<e.planningRenderEpoch<<",\"render_epoch\":"<<e.renderEpoch<<",\"setting_cycle\":"<<e.settingCycle<<",\"setting_cycle_observed\":"<<e.settingCycleObserved<<",\"operation_state_at_sample\":"<<q(e.operationStateAtSample)<<",\"producer_cycle\":"<<d.cycle<<",\"map_version\":"<<d.mapVersion<<",\"dynamic_id\":"<<d.operationID<<",\"local_start\":"<<d.localStart<<",\"local_end\":"<<d.localEnd<<",\"cumulative_start\":"<<d.cumulativeStart<<",\"cumulative_end\":"<<d.cumulativeEnd<<",\"generated_at_commit\":"<<d.generatedAtCommit<<",\"published_at_commit\":"<<d.publishedAtCommit<<",\"fifo_read_at_commit\":"<<e.fifoReadAtCommit<<",\"fifo_write_at_commit\":"<<e.fifoWriteAtCommit<<",\"pending_begin_local\":"<<e.pendingBeginLocal<<",\"pending_end_local\":"<<e.pendingEndLocal<<",\"pending_pcm_frames_at_commit\":"<<d.pendingPcmFramesAtCommit<<",\"pcm_generated_at_commit\":"<<d.pcmGeneratedAtCommit<<",\"cache_backed_at_commit\":"<<d.cacheBackedAtCommit<<",\"deferral_reason_code\":"<<int(d.reason)<<",\"source_hop\":"<<e.sourceHop<<",\"map_nodes\":"<<e.mapNodes.size()<<"}\n";
    std::ofstream nodes(out/"dynamic_map.nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(e.mapNodes.data()),e.mapNodes.size()*sizeof(long long));need(bool(nodes),"Map export failed");
}
int run(int argc,char** argv){
    need(argc==14,"INPUT PRESET NEW_OUT A B INITIAL TARGET WARM REQUEST_AFTER return|keep ENTRY_C(-1) CAPTURE_SECONDS SOURCE_SHA");
    const fs::path input=fs::absolute(argv[1]),out=fs::absolute(argv[3]);const std::string preset=argv[2],policy=argv[10];
    need(preset=="candidate"||preset=="baseline","preset");need(policy=="return"||policy=="keep","policy");
    ts::WavStreamReader wav(input);const auto a=std::stoull(argv[4]),b=std::stoull(argv[5]);
    const auto initial=std::stoul(argv[6]),target=std::stoul(argv[7]),warm=std::stoul(argv[8]),after=std::stoul(argv[9]);
    const auto entry=std::stoll(argv[11]);const auto seconds=std::stoul(argv[12]);const std::string sourceSha=argv[13];
    need(wav.channels()<=2&&a<b&&b<=wav.frames()&&warm<=8&&seconds>0&&seconds<=300&&sourceSha.size()==64,"fixture/capture bounds");
    need(policy!="keep"||(a==0&&b==wav.frames()),"KeepPosition is full-input only");
    need(entry<0||(std::uint64_t(entry)>=a&&std::uint64_t(entry)<b),"entry C must remain inside [A,B)");
    need(phase59::formalSpeed(std::uint32_t(initial))&&phase59::formalSpeed(std::uint32_t(target))&&initial!=target,"different valid target speed required");
    need(fs::create_directories(out),"refusing an existing export directory");
    std::ofstream expected(out/"EXPECTED.json");expected<<"{\"suite\":\"phase62_API_oracle_host\",\"expected\":1,\"input_sha256\":"<<q(sha(input))<<",\"binary_sha256\":"<<q(sha(fs::absolute(argv[0])))<<",\"source_inventory_sha256\":"<<q(sourceSha)<<",\"input_A\":"<<a<<",\"input_B\":"<<b<<",\"entry_C\":"<<entry<<",\"initial\":"<<initial<<",\"target\":"<<target<<",\"warm_cycles\":"<<warm<<",\"request_after\":"<<after<<",\"policy\":"<<q(policy)<<",\"capture_seconds\":"<<seconds<<",\"product_handoff_writes\":false}\n";expected.close();
    Capture capture(wav.sampleRate(),wav.channels(),unsigned(seconds));ProgressiveMacPlaybackEngine engine;
    ProgressiveOptions options;options.allowExperimentalLoops=true;options.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;options.initialSpeed=initial/1000000.;options.callbackRecordLimit=256;
    options.observerContext=&capture;options.observeEpochPcm=Capture::source;options.observeOutputPcm=Capture::processed;
    options.allocationHooks={[]()noexcept{allocations=0;counting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();counting=false;},[]()noexcept{return allocations;}};
    phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* test=allocate(37);release(test);phase61_heap_end();need(phase61_heap_allocations()&&phase61_heap_frees(),"malloc/free detector self-test");phase61_heap_reset();
    bool owned=false;std::string failure;std::optional<ApiOracleCommitEvidence> evidence;
    std::uint64_t externalID=0,loopID=0;std::size_t initialSeekCount=0;progressive::LoopSpeedOperation operation;
    try{
        need(engine.prepare(input,options),"prepare rejected");until(engine,[&]{return engine.getPlaybackState()==progressive::State::Ready;},"Ready timeout");
        const auto seek=[&]{if(entry<0)return;const auto c=context(engine);const auto r=engine.requestSeekToInputFrame(std::uint64_t(entry),c.inputGeneration,c.renderEpoch);need(r.accepted,"initial C Exact seek rejected");until(engine,[&]{for(const auto& op:engine.seekHistory())if(op.id==r.id){need(op.mode==progressive::SeekMode::Exact,"initial C actual method was not Exact");need(op.state!=progressive::SeekState::Failed&&op.state!=progressive::SeekState::Cancelled,"initial C seek failed");return op.state==progressive::SeekState::Completed;}return false;},"initial C seek timeout");need(engine.getCurrentPlaybackPosition().inputFrame==std::uint64_t(entry),"initial C was clamped");};
        progressive::LoopOptions lo;lo.startPolicy=policy=="keep"?progressive::LoopStartPolicy::KeepPosition:progressive::LoopStartPolicy::ReturnToA;
        if(policy=="keep"){until(engine,[&]{return engine.getPlaybackDiagnostics().pipeline.analysisDone;},"KeepPosition final analysis");seek();need(engine.play(),"normal Play rejected");until(engine,[&]{return capture.frames.load()>=2048;},"normal initial PCM");}
        const auto admission=engine.getCurrentPlaybackPosition();const auto admissionFrames=capture.frames.load();
        const auto loop=engine.requestLoopRange(a,b,context(engine),lo);need(loop.accepted,"Loop range rejected: "+loop.reason);loopID=loop.id;
        {std::ofstream f(out/"ADMISSION.json");f<<"{\"loop_id\":"<<loop.id<<",\"input_generation\":"<<admission.inputGeneration<<",\"source_session\":"<<admission.session<<",\"source_epoch\":"<<admission.renderEpoch<<",\"input_C_paired_sample\":"<<(admission.inputFrame?std::to_string(*admission.inputFrame):"null")<<",\"sampled_output\":"<<(admission.sampledOutputFrame?std::to_string(*admission.sampledOutputFrame):"null")<<",\"consumed_output\":"<<admission.outputFrame<<",\"observer_before_call\":"<<admissionFrames<<",\"observer_after_call\":"<<capture.frames.load()<<",\"control_call_window_not_atomic_activation_sample\":true}\n";}
        if(policy=="return"){until(engine,[&]{return engine.getLoopSnapshot().initialPositionComplete&&!engine.getPlaybackDiagnostics().retiringPipeline;},"ReturnToA preparation");seek();need(engine.play(),"Loop Play rejected");}
        initialSeekCount=engine.seekHistory().size();
        until(engine,[&]{const auto l=engine.getLoopSnapshot();need(l.cycles<=warm,"selected warm request cycle was missed");const auto base=l.lastBoundary?l.lastBoundary->callbackFrame:0;return l.cycles==warm&&capture.frames.load()>=base+after;},"request position timeout");
        const auto beforeRequest=engine.getLoopSnapshot();const auto beforeDiagnostics=engine.getPlaybackDiagnostics();
        {std::ofstream f(out/"REQUEST.json");f<<"{\"loop_id\":"<<beforeRequest.id<<",\"loop_cycle\":"<<beforeRequest.cycles<<",\"render_epoch\":"<<beforeRequest.currentRenderEpoch<<",\"cache_bytes\":"<<beforeRequest.cacheBytes<<",\"reuse_count\":"<<beforeRequest.reuseCount<<",\"worker_creations\":"<<beforeRequest.workerCreations<<",\"seed_restores\":"<<beforeRequest.seedRestores<<",\"cold_discarded\":"<<beforeRequest.coldDiscardedFrames<<",\"warm_discarded\":"<<beforeRequest.warmDiscardedFrames<<",\"cache_read_frames\":"<<beforeDiagnostics.pipeline.loopReuse.cacheReadFrames<<",\"fft_plan_creations\":"<<beforeDiagnostics.pipeline.loopReuse.fftPlanCreations<<",\"warm_fft_plan_creations\":"<<beforeDiagnostics.pipeline.loopReuse.warmFftPlanCreations<<",\"seed_clones\":"<<beforeDiagnostics.pipeline.loopReuse.seedClones<<",\"generated\":"<<beforeDiagnostics.generatedFrames<<",\"published\":"<<beforeDiagnostics.publishedFrames<<",\"consumed\":"<<beforeDiagnostics.consumedFrames<<",\"observer_output\":"<<capture.frames.load()<<"}\n";}
        const auto c=context(engine);const auto request=engine.requestLoopSpeed(target/1000000.,c);need(request.accepted&&!request.duplicate&&request.id,"external Loop speed request rejected/duplicate: "+request.reason);externalID=request.id;
        until(engine,[&]{need(!capture.errors,"capture exhausted/discontinuous");const auto op=engine.loopSpeedOperation(externalID);need(op.has_value(),"external request disappeared");operation=*op;
            need(op->state!=progressive::LoopSpeedState::Failed&&op->state!=progressive::LoopSpeedState::Cancelled&&op->state!=progressive::LoopSpeedState::Replaced,"request failed/cancelled/replaced: "+op->reason);
            if(op->committed&&!evidence)evidence=readApiOracleCommit(engine,externalID);
            return op->state==progressive::LoopSpeedState::Completed;},"external speed completion timeout");
        need(operation.dynamicOperationID&&operation.dynamicSession&&!operation.fixedBoundary,"only B fallback observed; current-cycle dynamic evidence required");
        if(!evidence)evidence=readApiOracleCommit(engine,externalID);
        until(engine,[&]{need(!capture.errors,"capture limit/order failure");return engine.getLoopSnapshot().cycles>=operation.cycle+2;},"dynamic B and one complete next fixed cycle");
        const auto atBoundary=capture.frames.load();until(engine,[&]{return capture.frames.load()>=atBoundary+wav.sampleRate()/200+1;},"next head correction capture");
        need(engine.pause(),"final Pause rejected");owned=true;
    }catch(const std::exception& e){failure=e.what();}
    // Freeze every callback reference before reading any host capture array.
    const auto savedHistory=engine.loopHistory();const auto savedSeeks=engine.seekHistory();const auto savedSeekCount=savedSeeks.size();
    {std::ofstream f(out/"SEEK.json");f<<'[';bool comma=false;for(const auto& op:savedSeeks){if(comma)f<<',';comma=true;f<<"{\"id\":"<<op.id<<",\"mode\":"<<q(op.mode==progressive::SeekMode::Exact?"Exact":"FastLocal")<<",\"state\":"<<q(progressive::name(op.state))<<",\"input_C\":"<<op.requestedInputFrame<<",\"output_C\":"<<op.outputStartFrame<<",\"epoch\":"<<op.renderEpoch<<",\"session\":"<<op.session<<'}';}f<<"]\n";}
    engine.stop();const auto d=engine.getPlaybackDiagnostics();const auto n=engine.getNativeDiagnostics();const auto owners=phase58::RealtimePipeline::executionOwnerCounts();
    const auto external=engine.loopSpeedHistory();exportExternal(out,external);exportCapture(out,capture);
    std::vector<phase59::SpeedOperation> internal;bool finalOwners=true;std::size_t matchingDynamicOwners=0;
    for(const auto& closed:engine.closedEpochs()){
        finalOwners&=closed.pipeline.finalDataAvailable&&!closed.droppedOperations;
        if(closed.pipeline.session==operation.dynamicSession){internal=closed.operations;++matchingDynamicOwners;}
    }
    if(d.pipeline.session==operation.dynamicSession)internal=engine.operationHistory();
    phase59::exportOperations(out,internal,std::uint32_t(initial));
    if(evidence)exportCommit(out,*evidence);
    std::ofstream history(out/"boundaries.csv");history<<"loop_id,cycle,setting_cycle,old_epoch,new_epoch,input_A,input_B,old_output_end,new_output_start,callback_frame,overlap,boundary_frames\n";
    for(const auto& e:savedHistory)history<<e.loopID<<','<<e.cycle<<','<<e.settingCycle<<','<<e.oldEpoch<<','<<e.newEpoch<<','<<e.inputA<<','<<e.inputBExclusive<<','<<e.oldOutputEnd<<','<<e.newOutputStart<<','<<e.callbackFrame<<','<<e.overlapFrames<<','<<e.boundaryProcessingFrames<<'\n';
    const bool healthy=owned&&failure.empty()&&initialSeekCount==savedSeekCount&&finalOwners&&d.pipeline.finalDataAvailable&&matchingDynamicOwners<=1&&!capture.errors&&!capture.nonfinite&&!capture.missing&&!d.missingFrames&&!d.underrunCalls&&d.callbackCppNew&&!*d.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees()&&owners.alive==0&&owners.peak<=2;
    std::ofstream result(out/"HOST_SUMMARY.json");result<<std::boolalpha<<"{\"suite\":\"phase62_API_oracle_host\",\"expected\":1,\"executed\":"<<int(healthy)<<",\"status\":"<<q(!healthy?"FAIL":evidence?"CAPTURED":"INCOMPLETE")<<",\"capture_complete\":"<<healthy<<",\"commit_evidence_available\":"<<bool(evidence)<<",\"loop_id\":"<<loopID<<",\"external_id\":"<<externalID<<",\"raw_frames\":"<<capture.rawUsed<<",\"output_frames\":"<<capture.frames.load()<<",\"channels\":"<<wav.channels()<<",\"rate\":"<<wav.sampleRate()<<",\"capture_errors\":"<<capture.errors<<",\"nonfinite\":"<<capture.nonfinite<<",\"missing_or_padding\":"<<capture.missing<<",\"owner_peak\":"<<owners.peak<<",\"owners_after_stop\":"<<owners.alive<<",\"final_owner_statistics\":"<<finalOwners<<",\"initial_seek_count\":"<<initialSeekCount<<",\"final_seek_count\":"<<savedSeekCount<<",\"callback_cpp_new\":"<<(d.callbackCppNew?std::to_string(*d.callbackCppNew):"null")<<",\"callback_malloc\":"<<phase61_heap_allocations()<<",\"callback_free\":"<<phase61_heap_frees()<<",\"device_rate\":"<<n.deviceRate<<",\"device_id\":"<<n.deviceId<<",\"device_channels\":"<<n.deviceChannels<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"worker_deadlines\":"<<d.workerDeadlineMisses<<",\"reason\":"<<q(failure.empty()&&!evidence?"bounded product commit/Map evidence adapter unavailable":failure)<<",\"independent_PCM_comparison\":\"PENDING_EXTERNAL_AUDIT\",\"mixer_gain\":\"NOT_RUN\",\"physical_loopback\":\"NOT_RUN\"}\n";
    return healthy&&evidence?0:2;
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=run(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return result;}
