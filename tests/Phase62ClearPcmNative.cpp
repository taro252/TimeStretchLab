// Independent DSP oracle: pre-generated, SHA-verified frozen fixed Exact RAW.
// LoopPcmAudit remains a separate product-RAW arithmetic check.
#define main includedPhase62NativeMain
#include "Phase62NativeTests.cpp"
#undef main
#include "prototype/Phase45PcmDigest.h"

namespace {
namespace phase58=ts::prototype::phase58;
using ClearClock=std::chrono::steady_clock;
constexpr const char* clearFrozenSha="de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748";
std::string clearFileSha(const std::filesystem::path& path){
    std::ifstream file(path,std::ios::binary);require(bool(file),"SHA input missing");ts::prototype::Phase45PcmDigest digest;std::array<char,65536> block{};
    while(file.read(block.data(),block.size())||file.gcount())digest.update(block.data(),std::size_t(file.gcount()));
    require(file.eof(),"SHA read failure");return digest.finish();
}
struct ClearPcmCapture {
    LoopPcmAudit audit;
    std::size_t channels=0,targetFrames=0,capacityFrames=0,recorded=0,spanCount=0;
    std::uint64_t firstCallback=0,captureErrors=0;
    std::vector<float> actual,newRaw,oldRaw;
    std::array<ProgressiveOutputSpan,256> spans{};
    std::atomic<std::uint64_t> frames{0},naturalBs{0};
    std::atomic<bool> armed{false},done{false};
    explicit ClearPcmCapture(std::size_t c,unsigned rate):audit(c),channels(c),targetFrames(rate/200+rate/20),capacityFrames(targetFrames+4096),actual(capacityFrames*c),newRaw(capacityFrames*c),oldRaw(capacityFrames*c){}
    static void source(void* context,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        LoopPcmAudit::source(&static_cast<ClearPcmCapture*>(context)->audit,pcm,n,at,generation,epoch,session);
    }
    static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& x=*static_cast<ClearPcmCapture*>(context);LoopPcmAudit::output(&x.audit,pcm,span);x.frames.fetch_add(span.frames,std::memory_order_relaxed);
        if(span.periodicBoundary&&span.periodOffset+span.frames==span.periodFrames)x.naturalBs.fetch_add(1,std::memory_order_relaxed);
        if(!x.armed.load(std::memory_order_relaxed)||x.done.load(std::memory_order_relaxed))return;
        if(!x.recorded){if(!span.mixedFrames)return;x.firstCallback=span.callbackFrame;}
        if(!span.frames||span.callbackFrame!=x.firstCallback+x.recorded||x.recorded+span.frames>x.capacityFrames||x.spanCount==x.spans.size()){
            ++x.captureErrors;x.done.store(true,std::memory_order_release);return;
        }
        const LoopPcmAudit::Raw* fresh=nullptr;const LoopPcmAudit::Raw* old=nullptr;
        for(const auto& slot:x.audit.raw){if(slot.epoch==span.newEpoch)fresh=&slot;if(slot.epoch==span.oldEpoch)old=&slot;}
        if(!fresh||fresh->next<span.newOutputOffset+span.newReceivedFrames||fresh->next-span.newOutputOffset>8192||(span.mixedFrames&&(!old||old->next<span.oldOutputOffset+span.oldReceivedFrames||old->next-span.oldOutputOffset>8192))){
            ++x.captureErrors;x.done.store(true,std::memory_order_release);return;
        }
        x.spans[x.spanCount++]=span;
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<x.channels;++c){const auto index=(x.recorded+i)*x.channels+c;
            x.actual[index]=pcm[c][i];x.newRaw[index]=i<span.newReceivedFrames?fresh->pcm[c][(span.newOutputOffset+i)%8192]:0.f;
            x.oldRaw[index]=i<span.mixedFrames&&i<span.oldReceivedFrames?old->pcm[c][(span.oldOutputOffset+i)%8192]:0.f;
        }
        x.recorded+=span.frames;if(x.recorded>=x.targetFrames)x.done.store(true,std::memory_order_release);
    }
};
void clearSaveRaw(const std::filesystem::path& path,const std::vector<float>& values,std::size_t count){
    require(count<=values.size(),"RAW save range");std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(values.data()),count*sizeof(float));require(bool(file),"RAW save failed");
}
std::vector<float> clearReadWindow(const std::filesystem::path& path,std::size_t start,std::size_t frames,std::size_t channels){
    require(std::filesystem::file_size(path)>=(start+frames)*channels*sizeof(float),"frozen RAW suffix too short");std::vector<float> values(frames*channels);
    std::ifstream file(path,std::ios::binary);file.seekg(start*channels*sizeof(float));require(bool(file.read(reinterpret_cast<char*>(values.data()),values.size()*sizeof(float))),"frozen RAW window read");
    for(const auto value:values)require(std::isfinite(value),"nonfinite frozen RAW");return values;
}
struct ClearPcmFixture {
    const std::filesystem::path output;ts::WavStreamReader wav;std::unique_ptr<ClearPcmCapture> capture;ProgressiveOptions options;ProgressiveMacPlaybackEngine engine;
    std::uint64_t loopID=0,b=0,dynamicB=0;std::size_t initialSeeks=0,referenceA=0,referenceB=0;unsigned rate=0;
    ClearPcmFixture(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder,std::size_t oa,std::size_t ob):output(folder),wav(input),capture(std::make_unique<ClearPcmCapture>(wav.channels(),wav.sampleRate())),referenceA(oa),referenceB(ob),rate(wav.sampleRate()){
        require(wav.frames()>=std::uint64_t(rate)*9&&wav.channels()<=2,"Clear fixture needs >=9s mono/stereo input");b=std::uint64_t(rate)*8;
        require(!oa&&ob>oa+rate/200&&ob-oa>96000,"independent fixed Map [A,B) must be long/uncached and A=0");
        options.allowExperimentalLoops=true;options.initialSpeed=1;options.preset=preset;options.callbackRecordLimit=4096;
        options.observerContext=capture.get();options.observeEpochPcm=ClearPcmCapture::source;options.observeOutputPcm=ClearPcmCapture::output;
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
        phase61_heap_reset();engine.prepare(input,options);wait(engine,State::Ready);const auto state=engine.getStateSnapshot();
        const auto receipt=engine.requestLoopRange(0,b,{state.inputGeneration,state.session,state.renderEpoch});require(receipt.accepted,"initial Loop rejected");loopID=receipt.id;
        until([&]{return engine.getLoopSnapshot().initialPositionComplete&&!engine.getPlaybackDiagnostics().retiringPipeline;},"initial ReturnToA Ready");initialSeeks=engine.seekHistory().size();
        require(engine.play(),"initial loop play");firstPcm(engine);until([&]{return capture->frames.load()>=rate/5;},"initial PCM");
    }
    ~ClearPcmFixture(){engine.stop();}
    void healthy(){const auto state=engine.getStateSnapshot();if(state.state==State::Failed)throw std::runtime_error(state.error);require(phase58::RealtimePipeline::executionOwnerCounts().peak<=2,"third execution owner");}
    template<class Predicate> void until(Predicate predicate,const char* reason){
        const auto deadline=ClearClock::now()+std::chrono::seconds(90);while(!predicate()){healthy();require(ClearClock::now()<deadline,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();
    }
    void run(const std::filesystem::path& fixedRaw){
        const auto speed=engine.setSpeed(.75);require(speed.result==ts::prototype::Phase39RequestResult::Accepted,"75 request rejected");
        until([&]{const auto loop=engine.getLoopSnapshot();return loop.dynamicOperationID&&loop.mapVersion&&loop.dynamicOutputEnd;},"75 current-cycle commit");
        const auto committed=engine.getLoopSnapshot();dynamicB=committed.dynamicOutputEnd;const auto beforeClear=engine.getPlaybackDiagnostics();
        require(!committed.cycles&&!committed.dynamicCycle&&beforeClear.currentEpochPresentedFrame+4096<dynamicB,"75 did not commit in first current cycle");
        const auto state=engine.getStateSnapshot();capture->armed.store(true,std::memory_order_release);
        const auto clear=engine.requestClearLoop(loopID,{state.inputGeneration,state.session,state.renderEpoch});require(clear.accepted,"Clear rejected after irreversible dynamic commit");
        require(!engine.getLoopSnapshot().enabled&&engine.getLoopSnapshot().clearPending,"Clear acceptance did not disable/preserve pending audio");
        until([&]{return capture->done.load(std::memory_order_acquire);},"Clear mixed PCM plus 50ms capture");
        until([&]{return !engine.getLoopSnapshot().clearPending&&!engine.getPlaybackDiagnostics().retiringPipeline;},"Clear normal Exact adoption/retirement");require(engine.pause(),"post-Clear pause");
        const auto loop=engine.getLoopSnapshot();const auto diagnostics=engine.getPlaybackDiagnostics();const auto boundaries=engine.loopHistory();
        require(capture->recorded>=capture->targetFrames&&!capture->captureErrors&&capture->spanCount,"bounded PCM capture failure");
        require(!loop.enabled&&!loop.clearPending&&!diagnostics.pipeline.loopReuse.enabled&&!diagnostics.pipeline.fastLocalSeek,"Clear revived Loop or used a local seek");
        require(diagnostics.pipeline.outputStartFrame==referenceB&&loop.cycles>=1&&boundaries.size()==loop.cycles&&loop.cycles==capture->naturalBs.load(),"Exact B or natural cycle count differs");
        require(engine.seekHistory().size()==initialSeeks,"internal continuation fabricated user seek");
        const auto length=referenceB-referenceA,n=std::size_t(rate/200);require(capture->firstCallback+n==dynamicB+loop.cycles*length,"Clear cumulative B differs from dynamic first L plus fixed subsequent L_i");
        for(std::size_t i=0;i<boundaries.size();++i){const auto& event=boundaries[i];require(event.cycle==i+1&&event.callbackFrame==dynamicB+i*length&&event.oldOutputEnd==(i?referenceB:dynamicB)&&event.newOutputStart==referenceA&&!event.overlapFrames,"natural L_i/Sigma L or dynamic B event mismatch");}
        const auto independent=clearReadWindow(fixedRaw,referenceB-n,n+capture->recorded,wav.channels());std::vector<float> expected(capture->recorded*wav.channels());
        std::uint64_t rawNewErrors=0,rawOldErrors=0,mixedErrors=0,outsideErrors=0,nonfinite=0;std::size_t mixedFrames=0,offset=0;
        std::ofstream spans(output/"captured_spans.jsonl");
        for(std::size_t s=0;s<capture->spanCount;++s){const auto& span=capture->spans[s];
            require(span.frames&&span.frames<=4096&&span.newOutputOffset==referenceB+offset&&span.newReceivedFrames==span.frames&&!span.oldMissingFrames&&!span.newMissingFrames&&!span.failurePaddingFrames&&!span.outputAffectedFrames,"Clear new RAW range or supply mismatch");
            require(!span.periodicBoundary&&!span.oldPeriodicBoundary&&!span.correctionBeforeMix,"Clear contract changed: scheduled continuation must mix RAW, not natural-cycle correction");
            const auto inMix=offset<n?std::min(span.frames,n-offset):0;require(span.mixedFrames==inMix,"Clear mixture length differs");
            if(inMix)require(span.transitionOffset==offset&&span.transitionLength==n&&span.oldOutputOffset==referenceB-n+offset&&span.oldReceivedFrames==inMix,"Clear old tail ownership or transition coordinate mismatch");
            spans<<"{\"capture_offset\":"<<offset<<",\"callback_frame\":"<<span.callbackFrame<<",\"frames\":"<<span.frames<<",\"old_epoch\":"<<span.oldEpoch<<",\"new_epoch\":"<<span.newEpoch<<",\"old_output\":"<<span.oldOutputOffset<<",\"new_output\":"<<span.newOutputOffset<<",\"mixed_frames\":"<<span.mixedFrames<<",\"transition_offset\":"<<span.transitionOffset<<",\"transition_length\":"<<span.transitionLength<<",\"old_periodic_correction\":false,\"new_periodic_correction\":false}\n";
            for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<wav.channels();++c){const auto k=offset+i,index=k*wav.channels()+c;const auto fresh=independent[(n+k)*wav.channels()+c];
                float value=fresh;if(std::bit_cast<std::uint32_t>(capture->newRaw[index])!=std::bit_cast<std::uint32_t>(fresh))++rawNewErrors;
                if(k<n){const auto previous=independent[k*wav.channels()+c];if(std::bit_cast<std::uint32_t>(capture->oldRaw[index])!=std::bit_cast<std::uint32_t>(previous))++rawOldErrors;
                    const float gain=float(k+1)/float(n);value=previous*(1.f-gain)+fresh*gain;
                }
                expected[index]=value;if(!std::isfinite(value)||!std::isfinite(capture->actual[index]))++nonfinite;
                if(std::bit_cast<std::uint32_t>(capture->actual[index])!=std::bit_cast<std::uint32_t>(value)){if(k<n)++mixedErrors;else ++outsideErrors;}
            }
            mixedFrames+=span.mixedFrames;offset+=span.frames;
        }
        spans.close();require(offset==capture->recorded&&mixedFrames==n,"Clear captured frame counts");
        clearSaveRaw(output/"processed_actual.f32",capture->actual,capture->recorded*wav.channels());clearSaveRaw(output/"new_actual_RAW.f32",capture->newRaw,capture->recorded*wav.channels());
        clearSaveRaw(output/"old_actual_RAW_tail.f32",capture->oldRaw,n*wav.channels());clearSaveRaw(output/"processed_independent_reference.f32",expected,expected.size());
        std::ofstream compare(output/"PCM_COMPARISON.json");compare<<"{\"independent_DSP\":\"frozen fixed Exact 750000\",\"old_RAW_bit_errors\":"<<rawOldErrors<<",\"new_RAW_bit_errors\":"<<rawNewErrors<<",\"mixed_bit_errors\":"<<mixedErrors<<",\"outside_window_bit_errors\":"<<outsideErrors<<",\"nonfinite\":"<<nonfinite<<",\"mixed_frames\":"<<n<<",\"captured_frames\":"<<capture->recorded<<",\"post_mix_frames\":"<<capture->recorded-n<<",\"channels\":"<<wav.channels()<<",\"channel_order\":\"interleaved input order\",\"old_period_tail_correction_in_Clear_window\":false,\"observer_stage\":\"pre-mainMixer gain 0.5\"}\n";compare.close();
        require(!rawNewErrors&&!rawOldErrors&&!mixedErrors&&!outsideErrors&&!nonfinite,"independent DSP RAW/final Clear PCM mismatch; see PCM_COMPARISON.json");
        const auto frozenFrames=capture->frames.load(),frozenCycles=loop.cycles;std::this_thread::sleep_for(std::chrono::milliseconds(50));require(engine.getPlaybackState()==State::Paused&&!engine.getLoopSnapshot().enabled&&capture->frames.load()==frozenFrames&&engine.getLoopSnapshot().cycles==frozenCycles,"Paused completed Clear auto-restarted");
        const auto native=engine.getNativeDiagnostics();engine.stop();const auto final=engine.getPlaybackDiagnostics();
        require(!capture->audit.errors&&!capture->audit.nonfinite,"product RAW/boundary arithmetic audit failure");
        require(!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&!loop.failurePaddingFrames&&!loop.outputAffectedFrames,"unexpected native supply/padding failure");
        require(diagnostics.callbackCppNew&&!*diagnostics.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback allocation/free");
        const auto owners=phase58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"execution owner lifetime cap");for(const auto& epoch:engine.closedEpochs())require(epoch.pipeline.finalDataAvailable,"unjoined retired owner");
        writePhase62Trace(output/"callbacks_all_spans.jsonl",engine.loopCallbackRecords());writePhase62Trace(output/"clock_anomaly_window.jsonl",engine.loopClockAnomalyRecords());
        std::ofstream report(output/"SUMMARY.json");report<<"{\"suite\":\"phase62_clear_final_PCM\",\"expected\":1,\"executed\":1,\"status\":\"PASS\",\"dynamic_first_L\":"<<dynamicB<<",\"fixed_L\":"<<length<<",\"natural_cycles\":"<<loop.cycles<<",\"clear_cumulative_B\":"<<capture->firstCallback+n<<",\"clear_connection_counted_as_cycle\":false,\"independent_DSP_RAW_and_final_PCM\":\"PASS\",\"normal_continuation_mode\":\"explicit fixed Exact\",\"natural_period_correction_independent_comparison\":\"NOT_RUN_IN_THIS_HOST\",\"mixer_gain_0_5\":\"NOT_RUN\",\"physical_loopback\":\"NOT_RUN\",\"callback_cpp_new\":"<<*diagnostics.callbackCppNew<<",\"callback_heap_calls\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()<<",\"owner_peak\":"<<owners.peak<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames<<",\"callback_deadlines_observed\":"<<native.deadlineMisses<<",\"worker_deadlines_observed\":"<<final.workerDeadlineMisses<<",\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";
    }
};
}
int main(int argc,char** argv){
    if(argc!=9){std::cerr<<"INPUT candidate|baseline NEW_OUTPUT_DIR FROZEN_FIXED_RAW OA OB FROZEN_FIXED_BINARY EXPECTED_RAW_SHA256\n";return 1;}
    int code=1;std::thread owner([&]{std::filesystem::path output;bool owned=false;try{
        const auto input=std::filesystem::absolute(argv[1]),raw=std::filesystem::absolute(argv[4]),oracle=std::filesystem::absolute(argv[7]);const std::string presetName=argv[2];require(presetName=="candidate"||presetName=="baseline","preset");
        require(clearFileSha(oracle)==clearFrozenSha,"frozen oracle binary SHA mismatch");require(clearFileSha(raw)==argv[8],"frozen RAW SHA mismatch");
        const auto oa=std::stoull(argv[5]),ob=std::stoull(argv[6]);output=std::filesystem::absolute(argv[3]);require(std::filesystem::create_directories(output),"new output directory required");owned=true;
        std::ofstream expected(output/"EXPECTED.json");expected<<"{\"suite\":\"phase62_clear_final_PCM\",\"expected\":1,\"preset\":"<<phase58::jsonString(presetName)<<",\"input_sha256\":"<<phase58::jsonString(clearFileSha(input))<<",\"binary_sha256\":"<<phase58::jsonString(clearFileSha(std::filesystem::absolute(argv[0])))<<",\"fixed_oracle_binary_sha256\":"<<phase58::jsonString(clearFrozenSha)<<",\"fixed_RAW_sha256\":"<<phase58::jsonString(argv[8])<<",\"fixed_OA\":"<<oa<<",\"fixed_OB\":"<<ob<<",\"input_A\":0,\"loop_millis\":8000,\"initial_speed\":1000000,\"target_speed\":750000,\"real_audio\":true,\"observer_stage\":\"pre-mainMixer\",\"comparison\":\"independent fixed Exact old/new RAW and independent Clear linear equation; natural tail/head correction is separate\"}\n";expected.close();
        phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"heap detector self-test");
        ClearPcmFixture test(input,presetName=="candidate"?Preset::Candidate:Preset::Baseline,output,oa,ob);test.run(raw);std::ifstream report(output/"SUMMARY.json");std::cout<<report.rdbuf();code=0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';if(owned){std::ofstream report(output/"SUMMARY.json");report<<"{\"suite\":\"phase62_clear_final_PCM\",\"expected\":1,\"executed\":0,\"status\":\"FAIL\",\"reason\":"<<phase58::jsonString(error.what())<<"}\n";}}});owner.join();return code;
}
