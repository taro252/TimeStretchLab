// Baseline-only native observations; use the recorded build/run manifest.
// Compile/link ONLY against baseline_source's 7c05319 product headers/library:
//   -I<...>/baseline_source/src  macos_progressive_playback_engine
// Suggested separate build directory: baseline_race_build_v1
// CLI: INPUT candidate|baseline NEW_OUTPUT_DIR [SECOND_INPUT]
// Run serially on the authorized audio host. The process driver must enforce
// a timeout: stop/join may itself expose an old-engine concurrency failure.
// No audio callback gate, allocation hook, DSP oracle, or physical loopback.
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "audio/WavStream.h"
#include <atomic>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

namespace {
using namespace ts::playback;
using State=progressive::State;
using Clock=std::chrono::steady_clock;
using Receipt=ts::prototype::Phase39RequestResult;
const char* boolean(bool value){return value?"true":"false";}
std::string quote(const std::string& value){
    std::string out="\"";
    for(unsigned char c:value){
        if(c=='\"'||c=='\\'){out+='\\';out+=char(c);}
        else if(c=='\n')out+="\\n";
        else if(c=='\r')out+="\\r";
        else if(c=='\t')out+="\\t";
        else if(c<32){const char* hex="0123456789abcdef";out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}
        else out+=char(c);
    }
    return out+'\"';
}
void check(bool value,const std::string& why){if(!value)throw std::runtime_error(why);}
template<class F> void until(ProgressiveMacPlaybackEngine& engine,F condition,unsigned milliseconds,const char* why){
    const auto deadline=Clock::now()+std::chrono::milliseconds(milliseconds);
    while(!condition()){
        if(engine.getPlaybackState()==State::Failed)throw std::runtime_error(engine.getPlaybackDiagnostics().error);
        check(Clock::now()<deadline,why);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
}
progressive::LoopContext context(ProgressiveMacPlaybackEngine& engine){
    const auto s=engine.getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};
}
struct OutputAudit {
    const std::size_t channels;
    std::atomic<std::uint64_t> frames{0},nonfinite{0},affected{0};
    explicit OutputAudit(std::size_t n):channels(n){}
    static void observe(void* pointer,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& self=*static_cast<OutputAudit*>(pointer);
        std::uint64_t invalid=0;
        for(std::size_t c=0;c<self.channels;++c)for(std::size_t i=0;i<span.frames;++i)
            invalid+=!std::isfinite(pcm[c][i]);
        self.nonfinite.fetch_add(invalid,std::memory_order_relaxed);
        self.affected.fetch_add(span.outputAffectedFrames+span.failurePaddingFrames,std::memory_order_relaxed);
        self.frames.fetch_add(span.frames,std::memory_order_release);
    }
};
struct Ledger {
    std::ofstream rows;
    unsigned executed=0,passed=0,reproduced=0,failed=0,incomplete=0;
    explicit Ledger(const std::filesystem::path& folder):rows(folder/"observations.jsonl"){
        check(bool(rows),"cannot create observations.jsonl");
    }
    void row(const char* name,const char* status,const std::string& fields){
        ++executed;
        const std::string s=status;
        passed+=s=="PASS";reproduced+=s=="REPRODUCED";
        failed+=s=="FAIL";incomplete+=s=="INCOMPLETE";
        const std::string value="{\"case\":"+quote(name)+",\"status\":"+quote(status)+fields+"}";
        rows<<value<<'\n';rows.flush();std::cout<<value<<std::endl;
    }
};
std::string sample(ProgressiveMacPlaybackEngine& engine,OutputAudit& audit){
    const auto s=engine.getStateSnapshot();const auto l=engine.getLoopSnapshot();
    const auto d=engine.getPlaybackDiagnostics();const auto p=engine.getCurrentPlaybackPosition();
    std::ostringstream out;
    out<<"{\"state\":"<<quote(progressive::name(s.state))<<",\"input_generation\":"<<s.inputGeneration
       <<",\"session\":"<<s.session<<",\"render_epoch\":"<<s.renderEpoch<<",\"loop_id\":"<<l.id
       <<",\"enabled\":"<<boolean(l.enabled)<<",\"clear_pending\":"<<boolean(l.clearPending)
       <<",\"cycle\":"<<l.cycles<<",\"speed_request_id\":"<<l.speedRequestID
       <<",\"requested_speed\":"<<l.requestedSpeed<<",\"applied_speed\":"<<l.appliedSpeed
       <<",\"generated\":"<<d.generatedFrames<<",\"published\":"<<d.publishedFrames
       <<",\"consumed_current_epoch\":"<<d.consumedFrames<<",\"output_observer_frames\":"<<audit.frames.load()
       <<",\"input_frame\":"<<(p.inputFrame?std::to_string(*p.inputFrame):"null")
       <<",\"missing_frames\":"<<d.missingFrames<<",\"underrun_calls\":"<<d.underrunCalls
       <<",\"stopped_speed\":"<<(s.stoppedSpeed?quote(name(s.stoppedSpeed->state)):"null")<<'}';
    return out.str();
}
int run(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder,
        const std::filesystem::path& nextInput){
    check(std::filesystem::create_directories(folder),"refusing an existing output directory");
    Ledger ledger(folder);bool setupComplete=false;std::string error;
    ts::WavStreamReader info(input),nextInfo(nextInput);
    check(info.frames()>=std::uint64_t(info.sampleRate())*9,"input must contain at least nine seconds");
    check(nextInfo.channels()==info.channels(),"replacement input channel count must match callback observer");
    OutputAudit audit(info.channels());ProgressiveMacPlaybackEngine engine;
    ProgressiveOptions options;options.preset=preset;options.initialSpeed=1;
    options.allowExperimentalLoops=true;options.callbackRecordLimit=256;
    options.observerContext=&audit;options.observeOutputPcm=OutputAudit::observe;
    try{
        check(engine.prepare(input,options),"prepare rejected");
        until(engine,[&]{return engine.getPlaybackState()==State::Ready;},40000,"initial Ready timeout");
        const auto initial=context(engine);
        progressive::LoopOptions loopOptions;loopOptions.startPolicy=progressive::LoopStartPolicy::ReturnToA;
        const auto loopReceipt=engine.requestLoopRange(0,std::uint64_t(info.sampleRate())*8,initial,loopOptions);
        check(loopReceipt.accepted,"ReturnToA admission: "+loopReceipt.reason);
        until(engine,[&]{return engine.getLoopSnapshot().initialPositionComplete;},40000,"initial loop preparation timeout");
        check(engine.play(),"initial play rejected");
        until(engine,[&]{return audit.frames.load()>=info.sampleRate()/4;},10000,"first output timeout");
        setupComplete=true;
        const auto activeContext=context(engine);const auto cycle=engine.getLoopSnapshot().cycles;
        const auto burstBefore=sample(engine,audit);
        bool accepted=true,ordered=true,comma=false;std::uint64_t previousID=0;std::ostringstream requests;requests<<'[';
        for(double speed:{.75,1.,.4,2.}){
            const auto c=context(engine);const auto r=engine.setSpeed(speed,c.session,c.inputGeneration,c.renderEpoch);
            accepted&=r.result==Receipt::Accepted;ordered&=r.id>previousID;
            if(comma)requests<<',';comma=true;
            requests<<"{\"speed\":"<<speed<<",\"id\":"<<r.id<<",\"result_enum\":"<<int(r.result)<<'}';
            previousID=r.id;std::this_thread::sleep_for(std::chrono::milliseconds(15));
        }
        requests<<']';std::this_thread::sleep_for(std::chrono::milliseconds(400));
        const auto burstLoop=engine.getLoopSnapshot();const bool beforeB=burstLoop.cycles==cycle;
        const bool latest=burstLoop.speedRequestID==previousID&&burstLoop.requestedSpeed==2.;
        const bool stillOld=burstLoop.appliedSpeed==1.;
        const char* burstStatus=!beforeB?"INCOMPLETE":!accepted||!ordered||!latest?"FAIL":stillOld?"REPRODUCED":"PASS";
        ledger.row("latest_requests_before_B",burstStatus,",\"requests\":"+requests.str()+",\"before\":"+burstBefore+
            ",\"after\":"+sample(engine,audit)+",\"before_B\":"+boolean(beforeB)+",\"latest_request_preserved\":"+boolean(latest)+
            ",\"reason\":"+quote(stillOld?"old loop branch defers replacement to B; no current-cycle PCM claim":"speed observation only; independent PCM NOT_RUN"));

        check(engine.pause(),"pause rejected");
        const auto pausedPosition=engine.getCurrentPlaybackPosition();const auto pausedLoop=engine.getLoopSnapshot();
        const auto pausedFrames=audit.frames.load();const auto pausedSample=sample(engine,audit);
        const auto c=context(engine);const auto pausedRequest=engine.setSpeed(.75,c.session,c.inputGeneration,c.renderEpoch);
        bool ready=false,held=true;
        const auto pauseEnd=Clock::now()+std::chrono::milliseconds(600);
        while(Clock::now()<pauseEnd){
            const auto s=engine.getStateSnapshot();const auto l=engine.getLoopSnapshot();
            held&=s.state==State::Paused&&l.id==pausedLoop.id&&l.cycles==pausedLoop.cycles&&
                audit.frames.load()==pausedFrames;
            ready|=s.stoppedSpeed&&s.stoppedSpeed->id==pausedRequest.id&&
                s.stoppedSpeed->speedMicros==750000&&s.stoppedSpeed->state==StoppedSpeedState::ReadyForResume;
            check(s.state!=State::Failed,s.error);std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        const bool inputHeld=engine.getCurrentPlaybackPosition().inputFrame==pausedPosition.inputFrame;
        ledger.row("paused_latest_ready_without_resume",pausedRequest.result!=Receipt::Accepted?"FAIL":ready&&held&&inputHeld?"PASS":"REPRODUCED",
            ",\"resume_calls\":0,\"observation_ms\":600,\"request_id\":"+std::to_string(pausedRequest.id)+
            ",\"ready_before_resume\":"+boolean(ready)+",\"input_C_held\":"+boolean(inputHeld)+
            ",\"before\":"+pausedSample+",\"after\":"+sample(engine,audit)+
            ",\"reason\":"+quote(ready?"ready state observed; full Exact PCM NOT_RUN":"bounded observation without Ready; old loop bypasses stopped-speed preparation"));
        ledger.row("paused_audible_output_and_cycles_stationary",held?"PASS":"FAIL",
            ",\"output_frames_before\":"+std::to_string(pausedFrames)+",\"output_frames_after\":"+std::to_string(audit.frames.load())+
            ",\"cycles_before\":"+std::to_string(pausedLoop.cycles)+",\"cycles_after\":"+std::to_string(engine.getLoopSnapshot().cycles));

        check(engine.resume(),"resume for Clear rejected");
        until(engine,[&]{return audit.frames.load()>pausedFrames;},10000,"resume produced no output");
        const auto clearBefore=sample(engine,audit);const auto clearFrames=audit.frames.load();
        const auto clearD=engine.getPlaybackDiagnostics();const auto clearAffected=audit.affected.load();
        // Original loop admission context is semantically valid across the
        // internal ReturnToA/automatic epoch switches in this baseline API.
        const auto clearReceipt=engine.requestClearLoop(loopReceipt.id,initial);
        const auto clearImmediate=engine.getLoopSnapshot();
        // Explicit loop-speed API distinguishes a reasoned Clear/no-loop reject
        // from a valid normal-playback speed change. It must not resurrect Loop.
        const auto clearingSpeed=engine.requestLoopSpeed(1.01,context(engine));
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
        const auto clearAfter=engine.getLoopSnapshot();const auto afterD=engine.getPlaybackDiagnostics();
        const bool clearSupply=clearReceipt.accepted&&!clearImmediate.enabled&&!clearAfter.enabled&&
            engine.getPlaybackState()==State::Playing&&audit.frames.load()>clearFrames&&
            afterD.missingFrames==clearD.missingFrames&&afterD.underrunCalls==clearD.underrunCalls&&
            audit.affected.load()==clearAffected&&!clearingSpeed.accepted&&!clearingSpeed.reason.empty();
        ledger.row("clear_enabled_off_and_supply_window",clearSupply?"PASS":"FAIL",
            ",\"accepted\":"+std::string(boolean(clearReceipt.accepted))+",\"observation_ms\":250,\"clear_pending_immediate\":"+
            boolean(clearImmediate.clearPending)+",\"clear_pending_after\":"+boolean(clearAfter.clearPending)+
            ",\"before\":"+clearBefore+",\"after\":"+sample(engine,audit)+
            ",\"speed_while_clear_accepted\":"+boolean(clearingSpeed.accepted)+",\"speed_rejection_reason\":"+quote(clearingSpeed.reason)+
            ",\"clear_completion_tested\":false,\"B_connection_PCM_compared\":false");

        // The old prepare API requires Stop before changing input. Do not call
        // prepare while Playing and mislabel its documented rejection a race.
        engine.stop();const auto stopped=engine.getLoopSnapshot();
        const auto stoppedFrames=audit.frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(120));
        const bool stopSafe=engine.getPlaybackState()==State::Stopped&&!stopped.enabled&&!stopped.clearPending&&
            audit.frames.load()==stoppedFrames;
        ledger.row("stop_cancels_old_loop",stopSafe?"PASS":"FAIL",",\"after\":"+sample(engine,audit));
        check(engine.prepare(nextInput,options),"replacement prepare rejected");
        until(engine,[&]{return engine.getPlaybackState()==State::Ready;},40000,"replacement Ready timeout");
        const auto replacement=engine.getStateSnapshot();
        const auto staleClear=engine.requestClearLoop(loopReceipt.id,activeContext);
        const auto staleSpeed=engine.setSpeed(.4,activeContext.session,activeContext.inputGeneration,activeContext.renderEpoch);
        bool noRevival=replacement.inputGeneration!=activeContext.inputGeneration&&!staleClear.accepted&&
            staleSpeed.result==Receipt::Stopped&&!engine.getLoopSnapshot().enabled;
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
        noRevival&=!engine.getLoopSnapshot().enabled&&!engine.getLoopSnapshot().clearPending&&engine.getPlaybackState()==State::Ready;
        const auto replacementFrames=audit.frames.load();check(engine.play(),"replacement play rejected");
        until(engine,[&]{return audit.frames.load()>replacementFrames;},10000,"replacement output timeout");
        std::this_thread::sleep_for(std::chrono::milliseconds(120));
        noRevival&=!engine.getLoopSnapshot().enabled&&!engine.getLoopSnapshot().clearPending;
        ledger.row("input_reprepare_and_stale_identity_no_resurrection",noRevival?"PASS":"FAIL",
            ",\"input_path_changed\":"+std::string(boolean(input!=nextInput))+
            ",\"input_content_change_verified\":false,\"old_input_generation\":"+std::to_string(activeContext.inputGeneration)+
            ",\"new_input_generation\":"+std::to_string(replacement.inputGeneration)+
            ",\"stale_clear_accepted\":"+boolean(staleClear.accepted)+",\"stale_speed_result_enum\":"+std::to_string(int(staleSpeed.result))+
            ",\"after\":"+sample(engine,audit)+",\"observation_after_Ready_ms\":250,\"observation_after_replay_ms\":120");
        engine.stop();
    }catch(const std::exception& exception){
        error=exception.what();
        ledger.row("execution_exception",setupComplete?"FAIL":"INCOMPLETE",",\"error\":"+quote(error));
        // A stuck old stop/join is intentionally visible as missing SUMMARY or
        // external timeout. No timeout may be converted into a successful run.
        engine.stop();
    }
    const auto d=engine.getPlaybackDiagnostics();const auto n=engine.getNativeDiagnostics();
    const bool finalFinite=audit.nonfinite.load()==0;
    ledger.row("observed_output_finite_and_no_affected_frames",finalFinite&&!audit.affected.load()?"PASS":"FAIL",
        ",\"nonfinite_all_channels\":"+std::to_string(audit.nonfinite.load())+
        ",\"output_affected_or_padding\":"+std::to_string(audit.affected.load())+
        ",\"independent_PCM_comparison\":\"NOT_RUN\"");
    const bool completed=ledger.executed==7&&ledger.failed==0&&ledger.incomplete==0&&finalFinite;
    // Seven observations: two unsupported contracts + five control assertions.
    std::ostringstream summary;
    summary<<"{\"suite\":\"phase62_baseline_races\",\"baseline_sha\":\"7c05319d8142ef53a70c95be4f214f293bb2428a\""
        <<",\"expected\":7,\"executed\":"<<ledger.executed<<",\"PASS\":"<<ledger.passed
        <<",\"REPRODUCED\":"<<ledger.reproduced<<",\"FAIL\":"<<ledger.failed<<",\"INCOMPLETE\":"<<ledger.incomplete
        <<",\"status\":"<<quote(ledger.failed?"FAIL":!completed?"INCOMPLETE":ledger.reproduced?"REPRODUCED":"OBSERVATIONS_COMPLETE")
        <<",\"nonfinite_all_channels\":"<<audit.nonfinite.load()<<",\"output_affected_or_padding\":"<<audit.affected.load()
        <<",\"missing_final_input_only\":"<<d.missingFrames<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames
        <<",\"preset\":"<<quote(preset==Preset::Candidate?"candidate":"baseline")<<",\"error\":"<<quote(error)
        <<",\"independent_PCM_comparison\":\"NOT_RUN\",\"callback_allocation_probe\":\"NOT_RUN\""
        <<",\"RT_deadline_approval\":\"NOT_RUN\",\"physical_loopback\":\"NOT_RUN\""
        <<",\"all_boundary_states_tested\":false,\"clear_B_completion_tested\":false,\"local_overall_go\":false}";
    std::ofstream result(folder/"SUMMARY.json");check(bool(result),"cannot create SUMMARY.json");
    result<<summary.str()<<'\n';result.flush();std::cout<<summary.str()<<std::endl;
    return completed?0:2;
}
}
int main(int argc,char** argv){
    if(argc!=4&&argc!=5){std::cerr<<"INPUT candidate|baseline NEW_OUTPUT_DIR [SECOND_INPUT]\n";return 1;}
    if(std::string(argv[2])!="candidate"&&std::string(argv[2])!="baseline"){std::cerr<<"invalid preset\n";return 1;}
    int result=1;
    // All engine construction, control calls, polling and destruction happen
    // on one ordinary application worker, never the main or audio thread.
    std::thread control([&]{try{
        result=run(argv[1],std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate,argv[3],argc==5?argv[4]:argv[1]);
    }catch(const std::exception& error){
        std::cout<<"{\"suite\":\"phase62_baseline_races\",\"expected\":7,\"executed\":0,\"status\":\"INCOMPLETE\",\"error\":"
            <<quote(error.what())<<",\"local_overall_go\":false}"<<std::endl;
    }});control.join();return result;
}
