// Actual renderer, off-line drive: neither HAL deadlines nor acoustic output.
#include "../src/platform/macos/ProgressiveMacPlaybackEngine.mm"
#define main includedPhase62DynamicPcmMain
#include "Phase62DynamicPcmTests.cpp"
#undef main
#include "prototype/Phase58FixAllocationProbe.h"
#include "Phase61CallbackMallocProbe.h"
#include <cstdlib>

// Verification host only, matching the existing native allocation probes.
namespace {thread_local bool handoffCounting=false;thread_local std::uint64_t handoffNew=0;
void handoffNote(){ts::prototype::phase58::noteDspAllocation();if(handoffCounting)++handoffNew;}}
void* operator new(std::size_t n){handoffNote();if(auto* p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){handoffNote();void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}
void operator delete(void* p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t)noexcept{std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}

using namespace ts::playback;
namespace {
constexpr const char* fixedSha="de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748";
struct HandoffCapture {
    std::size_t channels=0,currentEnd=0,nextLength=0,currentFrames=0,nextFrames=0,outputFrames=0,errors=0,nonfinite=0;
    std::uint64_t currentSession=0,nextSession=0;
    std::vector<float> currentRaw,nextRaw,output;
    static void source(void* pointer,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t,std::uint64_t,std::uint64_t session)noexcept{
        auto& x=*static_cast<HandoffCapture*>(pointer);const bool old=session==x.currentSession;
        if(!old&&session!=x.nextSession){++x.errors;return;}
        auto& frames=old?x.currentFrames:x.nextFrames;auto& data=old?x.currentRaw:x.nextRaw;
        if(at!=(old?frames:frames%x.nextLength)||at+n>(old?x.currentEnd:x.nextLength)||(frames+n)*x.channels>data.size()){++x.errors;return;}
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<x.channels;++c){auto value=pcm[c][i];data[(frames+i)*x.channels+c]=value;if(!std::isfinite(value))++x.nonfinite;}frames+=n;
    }
    static void processed(void* pointer,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& x=*static_cast<HandoffCapture*>(pointer);
        if(!span.frames||span.callbackFrame!=x.outputFrames||(x.outputFrames+span.frames)*x.channels>x.output.size()||span.mixedFrames||span.oldMissingFrames||span.newMissingFrames||span.outputAffectedFrames||span.failurePaddingFrames){++x.errors;return;}
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<x.channels;++c){auto value=pcm[c][i];x.output[(x.outputFrames+i)*x.channels+c]=value;if(!std::isfinite(value))++x.nonfinite;}x.outputFrames+=span.frames;
    }
};
void saveRaw(const fs::path& path,const std::vector<float>& pcm,std::size_t samples){
    require(samples<=pcm.size(),"save RAW range");std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(pcm.data()),samples*sizeof(float));require(bool(file),"RAW write failed");
}
std::vector<float> loadRaw(const fs::path& path,std::size_t frames,std::size_t channels){
    require(fs::file_size(path)==frames*channels*sizeof(float),"independent reference length");std::vector<float> pcm(frames*channels);std::ifstream file(path,std::ios::binary);
    require(bool(file.read(reinterpret_cast<char*>(pcm.data()),pcm.size()*sizeof(float))),"independent RAW read");for(float value:pcm)require(std::isfinite(value),"nonfinite independent RAW");return pcm;
}
float independentTail(float value,float last,float first,std::size_t j,std::size_t n){
    if(j+1==n)return last*.5f+first*.5f;const float t=float(j+1)/float(n);return value-(last-first)*.5f*(t*t*(3.f-2.f*t));
}
float independentHead(float value,float last,float first,std::size_t j,std::size_t n){
    if(!j)return last*.5f+first*.5f;const float t=1.f-float(j)/float(n);return value+(last-first)*.5f*(t*t*(3.f-2.f*t));
}
void invocation(const fs::path& path,const std::vector<std::string>& command){std::ofstream file(path);file<<'[';for(std::size_t i=0;i<command.size();++i)file<<(i?",":"")<<quote(command[i]);file<<"]\n";}
}
int main(int argc,char** argv){
    fs::path out;bool evidenceOwned=false;std::size_t observedFrames=0;int dynamicExit=-1,fixedExit=-1;
    try{
        require(argc==8||argc==9,"input initial_micros target_micros preset NEW_OUTPUT_DIR frozen_captured_reference frozen_fixed_seek_reference [callback=512]");
        const fs::path input=fs::absolute(argv[1]),dynamicOracle=fs::absolute(argv[6]),fixedOracle=fs::absolute(argv[7]);
        const auto initial=std::uint32_t(std::stoul(argv[2])),target=std::uint32_t(std::stoul(argv[3]));const std::string preset=argv[4];const bool candidate=preset=="candidate";
        const auto callback=argc==9?std::stoul(argv[8]):512UL;require(callback==64||callback==512||callback==4096,"callback is 64/512/4096");
        require((candidate||preset=="baseline")&&phase59::formalSpeed(initial)&&phase59::formalSpeed(target)&&initial!=target,"distinct formal speeds and valid preset required");
        require(fileSha(dynamicOracle)==capturedSha&&fileSha(fixedOracle)==fixedSha,"frozen oracle SHA differs from verified manifest");
        ts::WavStreamReader wav(input);require(wav.frames()>=std::uint64_t(wav.sampleRate())*8,"needs >=8 seconds, A=0 B=inputFrames");
        const auto initialLength=std::size_t(std::llround(wav.frames()/(initial/1000000.))),nextLength=std::size_t(std::llround(wav.frames()/(target/1000000.)));
        require(initialLength>96000&&nextLength>=512,"long uncached current and legal fixed next required");
        out=fs::absolute(argv[5]);require(!fs::exists(out),"new output directory required");fs::create_directories(out);evidenceOwned=true;
        std::ofstream expected(out/"EXPECTED.json");expected<<"{\"suite\":\"phase62_dynamic_handoff\",\"expected\":1,\"initial_micros\":"<<initial<<",\"target_micros\":"<<target
            <<",\"preset\":"<<quote(preset)<<",\"callback\":"<<callback<<",\"input_A\":0,\"input_B\":"<<wav.frames()<<",\"input_sha256\":"<<quote(fileSha(input))
            <<",\"binary_sha256\":"<<quote(fileSha(fs::absolute(argv[0])))<<",\"dynamic_oracle_sha256\":"<<quote(capturedSha)<<",\"fixed_oracle_sha256\":"<<quote(fixedSha)
            <<",\"reference_baseline\":"<<quote(baseline)<<",\"request_at_output\":8192,\"comparison\":\"frozen planner/Map/current RAW; frozen fixed next RAW; independent boundary and host gain equations\",\"realtime\":false}\n";expected.close();
        phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* allocation=allocate(37);release(allocation);phase61_heap_end();
        require(phase61_heap_allocations()&&phase61_heap_frees(),"heap interposition self-test failed");phase61_heap_reset();
        ts::prototype::phase58::Configuration config;config.speedMicros=initial;config.candidate=candidate;config.residentInput=true;config.verifyPcm=false;config.scheduling=ts::prototype::phase58::WorkerScheduling::AudioWorkgroup;
        auto source=std::make_unique<RealtimePipeline>(input,config);source->start();require(source->waitUntilReady(std::chrono::seconds(120)),"source Ready");waitFor([&]{return source->finalAnalysisAvailable();},"source final analysis");
        auto current=source->createLoopSeek(0,wav.frames(),initial);current->enableLoopReuse(0);source->stop();source.reset();
        current->start();require(current->waitUntilReady(std::chrono::seconds(120)),"current Ready");require(!current->diagnostics().loopReuse.cacheBytes,"current must retain uncached DSP");
        // Source is retired before the second execution owner is constructed.
        auto next=current->createLoopSeek(0,wav.frames(),target);next->enableLoopReuse(0);next->start();require(next->waitUntilReady(std::chrono::seconds(120)),"fixed next Ready before request");
        require(next->loopOutputStartFrame()==0&&next->loopOutputEndFrame()==nextLength,"fixed next A/B");
        require(current->setRealtimeRendering(true)&&next->setRealtimeRendering(true),"AudioWorkgroup arm");
        HandoffCapture capture;capture.channels=wav.channels();capture.currentEnd=initialLength;capture.nextLength=nextLength;capture.currentSession=current->diagnostics().session;capture.nextSession=next->diagnostics().session;
        const auto maxCurrent=std::size_t(std::ceil(wav.frames()/.4))+65536,hostCaptureBytes=(2*maxCurrent+6*nextLength)*wav.channels()*sizeof(float);
        require(hostCaptureBytes<=256ULL*1024*1024,"off-line host capture exceeds its separate 256 MiB bound; use an 8-second mandatory handoff fixture");
        capture.currentRaw.resize(maxCurrent*wav.channels());capture.nextRaw.resize(3*nextLength*wav.channels());capture.output.resize((maxCurrent+3*nextLength)*wav.channels());
        RenderTarget first,second;first.pipeline=current.get();second.pipeline=next.get();first.session=capture.currentSession;second.session=capture.nextSession;first.epoch=11;second.epoch=12;
        first.presented=0;second.presented=0;first.loopEnd=initialLength;second.loopEnd=nextLength;first.loopID=second.loopID=73;first.loopA=second.loopA=0;first.loopB=second.loopB=wav.frames();first.speedMicros=initial;second.speedMicros=target;
        RenderState state;state.target=&first;state.channels=unsigned(wav.channels());state.rate=wav.sampleRate();state.active=true;state.localEpoch=12;state.loopRecords.resize(256);
        state.observerContext=&capture;state.epochObserver=HandoffCapture::source;state.outputObserver=HandoffCapture::processed;
        state.allocationHooks={[]()noexcept{handoffNew=0;handoffCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();handoffCounting=false;},[]()noexcept{return handoffNew;}};
        std::array<std::array<float,4096>,2> pcm{};struct Buffers{UInt32 count;AudioBuffer data[2];}buffers{};buffers.count=state.channels;AudioTimeStamp stamp{};stamp.mFlags=kAudioTimeStampSampleTimeValid;BOOL silent=NO;
        std::size_t end=initialLength,total=end+2*nextLength+wav.sampleRate()/200+1,maxSpans=0;bool requested=false;phase59::RequestReceipt receipt;ts::prototype::phase58::LoopTransitionSnapshot terminal;
        std::ofstream spans(out/"output_spans.csv");spans<<"callback_frame,frames,new_epoch,new_output,period_frames,period_offset,boundary_frames,head,tail\n";
        while(capture.outputFrames<total){
            if(!requested&&capture.outputFrames==8192){
                receipt=current->requestLoopTransition(target,capture.currentFrames);require(receipt.result==ts::prototype::Phase39RequestResult::Accepted&&receipt.id,"dynamic request rejected despite Ready next");requested=true;
                waitFor([&]{terminal=current->loopTransition();require(terminal.state!=ts::prototype::phase58::LoopTransitionState::Rejected&&terminal.state!=ts::prototype::phase58::LoopTransitionState::Cancelled,"dynamic request rejected/cancelled");return terminal.state==ts::prototype::phase58::LoopTransitionState::Committed;},"dynamic commit");
                require(terminal.cycle==0&&terminal.localStart==0&&terminal.cumulativeStart==0&&terminal.localEnd==terminal.cumulativeEnd&&terminal.operationID==receipt.id,"dynamic terminal coordinates/identity");
                end=terminal.localEnd;capture.currentEnd=end;total=end+2*nextLength+wav.sampleRate()/200+1;require(end>capture.outputFrames+4096+wav.sampleRate()/200,"no legal current-cycle interval");
                auto& h=state.handoff;h.oldTarget=&first;h.newTarget=&second;h.output.prepare(wav.sampleRate());h.scheduledBoundary=h.periodic=h.loopCycle=true;h.committedDynamic=true;
                h.notBeforeCycle=terminal.cycle;h.boundaryEnd=end;h.loopID=73;h.inputA=0;h.inputB=wav.frames();h.phase=SwitchPhase::Requested;
            }
            auto count=std::min<std::size_t>(callback,total-capture.outputFrames);if(!requested)count=std::min<std::size_t>(count,8192-capture.outputFrames);
            waitFor([&]{require(!current->failed()&&!next->failed(),"handoff producer failure");const auto* owner=state.target.load();const auto left=owner==&first?end-first.presented.load():nextLength-second.presented.load();return owner->pipeline->available()>=std::min<std::size_t>(count,left)&&next->available()>=count;},"handoff FIFO");
            for(unsigned c=0;c<state.channels;++c)buffers.data[c]={1,UInt32(count*sizeof(float)),pcm[c].data()};
            render(&state,&silent,&stamp,static_cast<AVAudioFrameCount>(count),reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=count;observedFrames=capture.outputFrames;
            require(!state.loopMissed&&!capture.errors&&!capture.nonfinite,"renderer handoff gap/duplicate/padding/nonfinite");
            const auto& record=state.loopRecords[(state.loopRecordCount-1)%state.loopRecords.size()];maxSpans=std::max(maxSpans,record.spanCount);require(record.spanCount&&record.spanCount<=32,"callback span capacity");
            for(std::size_t i=0;i<record.spanCount;++i){const auto& s=record.spans[i];spans<<s.callbackFrame<<','<<s.frames<<','<<s.newEpoch<<','<<s.newOutputOffset<<','<<s.periodFrames<<','<<s.periodOffset<<','<<s.boundaryFrames<<','<<s.correctionHead<<','<<s.correctionTail<<'\n';}
        }
        state.active=false;state.handoff.phase=SwitchPhase::Idle;spans.close();require(current->setRealtimeRendering(false)&&next->setRealtimeRendering(false),"handoff disarm");current->stop();next->stop();
        const auto cd=current->diagnostics(),nd=next->diagnostics();require(cd.finalDataAvailable&&nd.finalDataAvailable&&!cd.failed&&!nd.failed&&!cd.missingFrames&&!nd.missingFrames&&!state.oldMissing&&!state.newMissing&&!state.loopSafetyFrames,"joined supply failure");
        require(!state.cppAllocations&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback allocation/free");
        require(capture.currentFrames==end&&capture.nextFrames==total-end&&capture.outputFrames==total&&first.presented==end&&state.loopCycles==3&&state.boundaryWritten==3,"PCM ownership, L_i, or cycles");
        for(std::uint64_t i=0;i<3;++i){const auto event=state.boundaryRing[i].read();require(event&&event->cycle==i+1&&event->callbackFrame==end+i*nextLength&&event->oldOutputEnd==(i?nextLength:end)&&event->newOutputStart==0&&!event->overlapFrames,"Sigma L boundary event");}
        const auto operations=current->speedOperations();const auto operation=std::find_if(operations.begin(),operations.end(),[&](const auto& op){return op.id==receipt.id;});
        require(operation!=operations.end()&&operation->appliedS>=0&&operation->completedS>=0&&operation->change.plan.completionOutputSample<static_cast<long long>(end),"request not completed inside current cycle");
        phase59::exportOperations(out,operations,initial);const auto map=current->dynamicTimeMap();require(std::size_t(std::llround(map.outputPositionForInputSample(double(wav.frames()))))==end,"committed Map B differs");
        std::ofstream nodes(out/"dynamic_map.nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(map.starts().data()),map.starts().size()*sizeof(long long));nodes.close();
        saveRaw(out/"current_actual.f32",capture.currentRaw,capture.currentFrames*wav.channels());saveRaw(out/"next_actual.f32",capture.nextRaw,capture.nextFrames*wav.channels());saveRaw(out/"processed_actual.f32",capture.output,total*wav.channels());
        current.reset();next.reset(); // Both product owners retire before oracle DSP.
        const auto owners=RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"execution owner lifetime cap/retirement");
        const std::vector<std::string> dynamicCommand{dynamicOracle.string(),input.string(),std::to_string(initial),preset,out.string(),(out/"dynamic_reference.f32").string(),(out/"dynamic_reference").string()};
        invocation(out/"DYNAMIC_REFERENCE_COMMAND.json",dynamicCommand);dynamicExit=runFrozen(dynamicCommand,out/"dynamic_reference.log");require(!dynamicExit&&fs::is_regular_file(out/"dynamic_reference.json")&&fs::is_regular_file(out/"dynamic_reference.plans.csv"),"frozen dynamic replay/final statistics failed");
        equalFiles(out/"current_actual.f32",out/"dynamic_reference.f32",wav.channels(),true,out/"first_current_mismatch.json");equalFiles(out/"dynamic_map.nodes.bin",out/"dynamic_reference.nodes.bin",wav.channels(),false,out/"first_map_mismatch.json");
        const std::vector<std::string> fixedCommand{fixedOracle.string(),input.string(),std::to_string(target),preset,(out/"fixed_reference.f32").string(),"0",std::to_string(wav.frames())};
        invocation(out/"FIXED_REFERENCE_COMMAND.json",fixedCommand);fixedExit=runFrozen(fixedCommand,out/"fixed_reference.log");require(!fixedExit&&fs::file_size(out/"fixed_reference.log")>0,"frozen fixed Exact failed/final statistics missing");
        const auto oldRaw=loadRaw(out/"dynamic_reference.f32",end,wav.channels()),newRaw=loadRaw(out/"fixed_reference.f32",nextLength,wav.channels());
        for(std::size_t i=0;i<capture.nextFrames;++i)for(std::size_t c=0;c<wav.channels();++c)require(std::bit_cast<std::uint32_t>(capture.nextRaw[i*wav.channels()+c])==std::bit_cast<std::uint32_t>(newRaw[(i%nextLength)*wav.channels()+c]),"next fixed RAW sequence/bits differ");
        std::vector<float> processed(total*wav.channels()),gained(total*wav.channels()),expectedGain(total*wav.channels());std::size_t outside=0,inside=0;
        const auto oldWindow=std::min<std::size_t>(wav.sampleRate()/200,end/4),newWindow=std::min<std::size_t>(wav.sampleRate()/200,nextLength/4);
        for(std::size_t i=0;i<total;++i)for(std::size_t c=0;c<wav.channels();++c){float value=0;bool corrected=false;
            if(i<end){value=oldRaw[i*wav.channels()+c];if(i>=end-oldWindow){value=independentTail(value,oldRaw[(end-1)*wav.channels()+c],newRaw[c],i-(end-oldWindow),oldWindow);corrected=true;}}
            else{const auto frame=i-end,at=frame%nextLength,cycle=frame/nextLength;value=newRaw[at*wav.channels()+c];
                if(at>=nextLength-newWindow){value=independentTail(value,newRaw[(nextLength-1)*wav.channels()+c],newRaw[c],at-(nextLength-newWindow),newWindow);corrected=true;}
                else if(at<newWindow){value=independentHead(value,cycle?newRaw[(nextLength-1)*wav.channels()+c]:oldRaw[(end-1)*wav.channels()+c],newRaw[c],at,newWindow);corrected=true;}}
            const auto sample=i*wav.channels()+c;processed[sample]=value;require(std::isfinite(value)&&std::bit_cast<std::uint32_t>(capture.output[sample])==std::bit_cast<std::uint32_t>(value),corrected?"independent boundary PCM differs":"PCM changed outside correction windows");
            corrected?++inside:++outside;gained[sample]=capture.output[sample]*.5f;expectedGain[sample]=value/2.f;require(std::bit_cast<std::uint32_t>(gained[sample])==std::bit_cast<std::uint32_t>(expectedGain[sample]),"host 0.5 gain equation");
        }
        saveRaw(out/"processed_reference.f32",processed,processed.size());saveRaw(out/"host_gain_05_actual.f32",gained,gained.size());saveRaw(out/"host_gain_05_reference.f32",expectedGain,expectedGain.size());
        require(fileSha(dynamicOracle)==capturedSha&&fileSha(fixedOracle)==fixedSha,"oracle changed during comparison");
        std::ofstream result(out/"SUMMARY.json");result<<"{\"suite\":\"phase62_dynamic_handoff\",\"expected\":1,\"executed\":1,\"status\":\"PASS\",\"initial_micros\":"<<initial<<",\"target_micros\":"<<target<<",\"preset\":"<<quote(preset)<<",\"callback\":"<<callback
            <<",\"current_L\":"<<end<<",\"next_L\":"<<nextLength<<",\"Sigma_L_three_periods\":"<<end+2*nextLength<<",\"output_frames\":"<<total<<",\"cycles\":3,\"map_version\":"<<terminal.mapVersion<<",\"operation_id\":"<<receipt.id
            <<",\"applied_output\":"<<operation->change.plan.appliedOutputSample<<",\"completion_output\":"<<operation->change.plan.completionOutputSample<<",\"generated_at_commit\":"<<terminal.generatedAtCommit<<",\"published_at_commit\":"<<terminal.publishedAtCommit
            <<",\"independent_planner_Map_RAW\":true,\"independent_fixed_next_RAW\":true,\"independent_final_PCM\":true,\"outside_window_samples\":"<<outside<<",\"inside_window_samples\":"<<inside<<",\"max_spans\":"<<maxSpans
            <<",\"callback_cpp_new\":"<<state.cppAllocations.load()<<",\"callback_heap_allocations\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()<<",\"missing\":0,\"padding\":0,\"nonfinite\":0,\"max_product_owners\":2,\"host_capture_bytes\":"<<hostCaptureBytes
            <<",\"host_gain_05_equation\":\"PASS\",\"native_mixer_gain\":\"NOT_RUN\",\"realtime\":false,\"physical_loopback\":\"NOT_RUN\",\"processed_pcm_sha256\":"<<quote(fileSha(out/"processed_actual.f32"))<<",\"dynamic_oracle_exit\":"<<dynamicExit<<",\"fixed_oracle_exit\":"<<fixedExit<<"}\n";
        result.close();std::ifstream report(out/"SUMMARY.json");std::cout<<report.rdbuf();return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';if(evidenceOwned){std::ofstream result(out/"SUMMARY.json");result<<"{\"suite\":\"phase62_dynamic_handoff\",\"expected\":1,\"executed\":0,\"status\":\"FAIL\",\"observed_frames\":"<<observedFrames<<",\"reason\":"<<quote(error.what())<<",\"dynamic_oracle_exit\":"<<dynamicExit<<",\"fixed_oracle_exit\":"<<fixedExit<<",\"realtime\":false}\n";}return 1;}
}
