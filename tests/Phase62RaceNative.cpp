// Phase62RaceNative: current-engine variant of BaselineRaceProbe.
// Link the current
// macos_progressive_playback_engine target and its PUBLIC src include path.
// Suggested prototype target: phase62_race_native. No baseline library/header.
// CLI: INPUT candidate|baseline NEW_OUTPUT_DIR [SECOND_INPUT]
// Run serially on the authorized audio host. The process driver must enforce
// a timeout: a stuck stop/join must retain a failed/incomplete observation.
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
namespace phase58=ts::prototype::phase58;
// The hook is invoked by the ordinary seek worker outside the engine mutex.
// It holds a published boundary preparation before offering the DSP transaction;
// neither this function nor the callback calls an engine control API.
struct WorkerPublishedGate {
    std::atomic<bool> armed{false},entered{false},released{false},expired{false};
    void release()noexcept{released.store(true,std::memory_order_release);}
    static void event(void* context,ProgressiveControlTestPoint point)noexcept{
        auto& gate=*static_cast<WorkerPublishedGate*>(context);
        if(point!=ProgressiveControlTestPoint::SwitchPublished||!gate.armed.exchange(false))return;
        gate.entered.store(true,std::memory_order_release);
        const auto deadline=Clock::now()+std::chrono::seconds(30);
        while(!gate.released.load(std::memory_order_acquire)&&Clock::now()<deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if(!gate.released.load(std::memory_order_acquire))gate.expired.store(true);
    }
};
struct ReleaseGateOnExit {
    WorkerPublishedGate& gate;
    ~ReleaseGateOnExit(){gate.release();}
};
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
       <<",\"stopped_speed\":"<<(s.stoppedSpeed?quote(name(s.stoppedSpeed->state)):"null")
       <<",\"dynamic_operation_id\":"<<l.dynamicOperationID<<",\"dynamic_speed_request_id\":"<<l.dynamicSpeedRequestID
       <<",\"dynamic_cycle\":"<<l.dynamicCycle<<",\"dynamic_B\":"<<l.dynamicOutputEnd<<",\"map_version\":"<<l.mapVersion
       <<",\"speed_defer_reason\":"<<quote(l.speedDeferReason)<<'}';
    return out.str();
}
int run(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder,
        const std::filesystem::path& nextInput){
    check(std::filesystem::create_directories(folder),"refusing an existing output directory");
    Ledger ledger(folder);bool setupComplete=false;std::string error;
    ts::WavStreamReader info(input),nextInfo(nextInput);
    check(info.frames()>=std::uint64_t(info.sampleRate())*9,"input must contain at least nine seconds");
    check(nextInfo.channels()==info.channels(),"replacement input channel count must match callback observer");
    OutputAudit audit(info.channels());WorkerPublishedGate gate;ProgressiveMacPlaybackEngine engine;
    ReleaseGateOnExit releaseGateOnExit{gate}; // destroyed before engine, including stack unwinding
    ProgressiveOptions options;options.preset=preset;options.initialSpeed=1;
    options.allowExperimentalLoops=true;options.callbackRecordLimit=256;
    options.observerContext=&audit;options.observeOutputPcm=OutputAudit::observe;
    options.controlTestHooks={&gate,WorkerPublishedGate::event};
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
        const auto request=[&](double speed){
            const auto c=context(engine);const auto r=engine.setSpeed(speed,c.session,c.inputGeneration,c.renderEpoch);
            accepted&=r.result==Receipt::Accepted;ordered&=r.id>previousID;
            if(comma)requests<<',';comma=true;
            requests<<"{\"speed\":"<<speed<<",\"id\":"<<r.id<<",\"result_enum\":"<<int(r.result)<<'}';
            previousID=r.id;
        };
        // Restrict the comparison to replacing an UNCOMMITTED 75% owner.
        // A committed 75% owner must retain its B continuation, so arbitrary
        // wall-clock bursts cannot legitimately require 200% in this cycle.
        gate.armed.store(true);request(.75);
        until(engine,[&]{return gate.entered.load(std::memory_order_acquire);},30000,
            "75 preparation did not reach the normal-worker pre-offer gate");
        check(!gate.expired.load(),"normal-worker pre-offer gate watchdog expired");
        const auto preOffer=engine.getLoopSnapshot();
        check(preOffer.cycles==cycle&&!preOffer.dynamicOperationID,
            "75 already committed or original cycle ended before pre-offer gate");
        const auto gatedSample=sample(engine,audit);const auto gatedFrames=audit.frames.load();
        for(double speed:{1.,.4,2.}){request(speed);std::this_thread::sleep_for(std::chrono::milliseconds(15));}
        requests<<']';
        const bool outputAdvancedWhileGated=audit.frames.load()>gatedFrames;
        const auto gatedLatest=sample(engine,audit);
        gate.release();
        const auto appliedWaitStart=Clock::now();
        bool currentCycleApplied=false,applicationCompleted=false;
        ts::prototype::phase59::SpeedOperation actualOperation;
        const auto applyDeadline=appliedWaitStart+std::chrono::seconds(2);
        do{
            const auto l=engine.getLoopSnapshot();const auto s=engine.getStateSnapshot();
            check(s.state!=State::Failed,s.error);
            check(!gate.expired.load(),"normal-worker pre-offer gate watchdog expired");
            if(l.cycles!=cycle)break;
            for(const auto& operation:engine.operationHistory()){
                if(l.dynamicSpeedRequestID==previousID&&l.dynamicOperationID==operation.id&&
                   l.dynamicCycle==cycle&&operation.target==2000000&&operation.inputGeneration==activeContext.inputGeneration&&
                   operation.appliedS>=0){
                    actualOperation=operation;
                    currentCycleApplied=l.appliedSpeed==2.;
                    applicationCompleted=operation.completedS>=0&&operation.state==ts::prototype::phase59::OperationState::Completed;
                }
            }
            if(currentCycleApplied&&applicationCompleted)break;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }while(Clock::now()<applyDeadline);
        const auto burstLoop=engine.getLoopSnapshot();const bool beforeB=burstLoop.cycles==cycle;
        const bool latest=burstLoop.speedRequestID==previousID&&burstLoop.requestedSpeed==2.;
        const bool actualLatest=currentCycleApplied&&applicationCompleted&&burstLoop.appliedSpeed==2.;
        const char* burstStatus=!beforeB?"INCOMPLETE":accepted&&ordered&&latest&&actualLatest&&outputAdvancedWhileGated?"PASS":"FAIL";
        ledger.row("latest_requests_before_B",burstStatus,",\"requests\":"+requests.str()+",\"before\":"+burstBefore+
            ",\"scope\":\"replacement before dynamic commit; committed replacement is a separate native gate\""
            ",\"normal_worker_gate\":\"SwitchPublished before DSP offer\",\"callback_gate\":false,\"gate_watchdog_seconds\":30"
            ",\"gate_before_replacements\":"+gatedSample+",\"gate_after_replacements\":"+gatedLatest+
            ",\"output_advanced_while_worker_gated\":"+boolean(outputAdvancedWhileGated)+
            ",\"after\":"+sample(engine,audit)+",\"before_B\":"+boolean(beforeB)+",\"latest_request_preserved\":"+boolean(latest)+
            ",\"observation_ms\":"+std::to_string(std::chrono::duration<double,std::milli>(Clock::now()-appliedWaitStart).count())+
            ",\"latest_dynamic_applied\":"+boolean(currentCycleApplied)+",\"latest_dynamic_completed\":"+boolean(applicationCompleted)+
            ",\"operation_id\":"+std::to_string(actualOperation.id)+",\"operation_state\":"+quote(ts::prototype::phase59::name(actualOperation.state))+
            ",\"applied_s\":"+std::to_string(actualOperation.appliedS)+",\"completed_s\":"+std::to_string(actualOperation.completedS)+
            ",\"published_at_plan\":"+std::to_string(actualOperation.publishedAtPlan)+",\"consumed_at_apply\":"+std::to_string(actualOperation.consumedAtApply)+
            ",\"reason\":"+quote(!beforeB?"current-cycle precondition expired":actualLatest?"latest operation completed while still in original cycle":"latest target not observably completed before deadline")+
            ",\"independent_PCM_comparison\":\"NOT_RUN\"");

        check(engine.pause(),"pause rejected");
        const auto pausedPosition=engine.getCurrentPlaybackPosition();const auto pausedLoop=engine.getLoopSnapshot();
        check(pausedPosition.inputFrame.has_value(),"paired stopped input C unavailable");
        const auto pausedDiagnostic=engine.getPlaybackDiagnostics();
        const auto pausedSeekCount=engine.seekHistory().size();
        const auto pausedFrames=audit.frames.load();const auto pausedSample=sample(engine,audit);
        const auto c=context(engine);const auto pausedRequest=engine.setSpeed(.75,c.session,c.inputGeneration,c.renderEpoch);
        bool ready=false,held=true,inputHeld=true,fifoHeld=true,retiredBeforeResume=false;
        StoppedSpeedOperation prepared;
        const auto pauseWaitStart=Clock::now();const auto pauseEnd=pauseWaitStart+std::chrono::seconds(5);
        const auto observeHold=[&]{
            const auto s=engine.getStateSnapshot();const auto l=engine.getLoopSnapshot();
            const auto p=engine.getCurrentPlaybackPosition();const auto d=engine.getPlaybackDiagnostics();
            held&=s.state==State::Paused&&!s.resumePending&&l.enabled&&l.id==pausedLoop.id&&
                l.startFrame==pausedLoop.startFrame&&l.endFrameExclusive==pausedLoop.endFrameExclusive&&
                l.cycles==pausedLoop.cycles&&audit.frames.load()==pausedFrames&&engine.seekHistory().size()==pausedSeekCount;
            inputHeld&=p.inputFrame==pausedPosition.inputFrame&&p.inputGeneration==pausedPosition.inputGeneration;
            if(d.renderEpoch==pausedDiagnostic.renderEpoch)fifoHeld&=d.consumedFrames==pausedDiagnostic.consumedFrames;
            else fifoHeld&=d.consumedFrames==d.pipeline.outputStartFrame&&d.currentEpochPresentedFrame==d.pipeline.outputStartFrame;
            check(s.state!=State::Failed,s.error);
            if(s.stoppedSpeed&&s.stoppedSpeed->id==pausedRequest.id)prepared=*s.stoppedSpeed;
        };
        do{
            observeHold();
            ready=prepared.id==pausedRequest.id&&prepared.speedMicros==750000&&
                prepared.state==StoppedSpeedState::ReadyForResume;
            if(ready||prepared.state==StoppedSpeedState::Failed||prepared.state==StoppedSpeedState::Cancelled||
               prepared.state==StoppedSpeedState::Replaced)break;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }while(Clock::now()<pauseEnd);
        if(ready){
            observeHold();
            const auto d=engine.getPlaybackDiagnostics();
            bool sourceJoined=false;
            for(const auto& old:engine.closedEpochs())if(old.pipeline.session==prepared.sourceSession)
                sourceJoined|=old.pipeline.finalDataAvailable;
            retiredBeforeResume=sourceJoined&&!d.retiringPipeline;
            ready&=prepared.positionCaptured&&prepared.resumeInputFrame==*pausedPosition.inputFrame&&
                prepared.inputGeneration==pausedPosition.inputGeneration&&prepared.loopID==pausedLoop.id&&
                prepared.cycle==pausedLoop.cycles&&prepared.preparationVersion&&
                prepared.mode==progressive::SeekMode::Exact&&!prepared.outputStarted;
        }
        ledger.row("paused_latest_ready_without_resume",
            pausedRequest.result==Receipt::Accepted&&ready&&held&&inputHeld&&fifoHeld&&retiredBeforeResume?"PASS":"FAIL",
            ",\"resume_calls\":0,\"observation_ms\":"+std::to_string(std::chrono::duration<double,std::milli>(Clock::now()-pauseWaitStart).count())+
            ",\"request_id\":"+std::to_string(pausedRequest.id)+",\"ready_before_resume\":"+boolean(ready)+",\"input_C_held\":"+boolean(inputHeld)+
            ",\"FIFO_not_consumed\":"+boolean(fifoHeld)+",\"retired_before_resume\":"+boolean(retiredBeforeResume)+
            ",\"preparation_version\":"+std::to_string(prepared.preparationVersion)+
            ",\"before\":"+pausedSample+",\"after\":"+sample(engine,audit)+
            ",\"reason\":"+quote(ready?"matching Exact Ready and retirement observed; independent PCM NOT_RUN":"matching Resume-free Ready or required identity/retirement missing"));
        ledger.row("paused_audible_output_and_cycles_stationary",held?"PASS":"FAIL",
            ",\"output_frames_before\":"+std::to_string(pausedFrames)+",\"output_frames_after\":"+std::to_string(audit.frames.load())+
            ",\"cycles_before\":"+std::to_string(pausedLoop.cycles)+",\"cycles_after\":"+std::to_string(engine.getLoopSnapshot().cycles));

        check(engine.resume(),"resume for Clear rejected");
        until(engine,[&]{return audit.frames.load()>pausedFrames;},10000,"resume produced no output");
        const auto clearBefore=sample(engine,audit);const auto clearFrames=audit.frames.load();
        const auto clearD=engine.getPlaybackDiagnostics();const auto clearAffected=audit.affected.load();
        // Original loop admission context is semantically valid across the
        // internal ReturnToA/automatic epoch switches in the loop API.
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

        // The prepare API requires Stop before changing input. Do not call
        // prepare while Playing and mislabel its documented rejection a race.
        engine.stop();const auto stopped=engine.getLoopSnapshot();
        const auto stoppedFrames=audit.frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(120));
        const auto firstStoppedOwners=phase58::RealtimePipeline::executionOwnerCounts();
        const bool stopSafe=engine.getPlaybackState()==State::Stopped&&!stopped.enabled&&!stopped.clearPending&&
            audit.frames.load()==stoppedFrames&&firstStoppedOwners.alive==0&&firstStoppedOwners.peak<=2;
        ledger.row("stop_cancels_old_loop",stopSafe?"PASS":"FAIL",",\"after\":"+sample(engine,audit)+
            ",\"product_owners_alive_after_stop\":"+std::to_string(firstStoppedOwners.alive)+
            ",\"product_owners_peak\":"+std::to_string(firstStoppedOwners.peak));
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

        // New current-cycle observation, separate from the seven historical
        // baseline comparisons. Independent full PCM is tested by the API oracle host.
        until(engine,[&]{return engine.getPlaybackDiagnostics().pipeline.analysisDone;},30000,
            "replacement input analysis did not complete for KeepPosition");
        check(engine.getPlaybackState()==State::Playing,"KeepPosition setup reached EOS before its first cycle");
        const auto keepContext=context(engine);
        progressive::LoopOptions keepOptions;keepOptions.startPolicy=progressive::LoopStartPolicy::KeepPosition;
        const auto keepReceipt=engine.requestLoopRange(0,nextInfo.frames(),keepContext,keepOptions);
        check(keepReceipt.accepted,"KeepPosition full-input admission: "+keepReceipt.reason);
        until(engine,[&]{const auto l=engine.getLoopSnapshot();check(!l.cycles,"KeepPosition first cycle ended before Armed observation");
            return l.state==progressive::LoopState::Armed||l.initialPositionComplete;},30000,
            "KeepPosition initial boundary preparation did not become Armed");
        const auto keepBefore=engine.getLoopSnapshot();const auto keepBeforeSample=sample(engine,audit);
        check(keepBefore.cycles==0,"KeepPosition first-cycle precondition expired before speed request");
        const auto keepFrames=audit.frames.load();const auto keepAffected=audit.affected.load();
        const auto keepDiagnostic=engine.getPlaybackDiagnostics();
        const auto keepSpeedContext=context(engine);
        const auto keepSpeed=engine.setSpeed(.75,keepSpeedContext.session,keepSpeedContext.inputGeneration,keepSpeedContext.renderEpoch);
        const auto keepImmediate=engine.getLoopSnapshot();
        until(engine,[&]{auto op=engine.loopSpeedOperation(keepSpeed.id);return op&&progressive::terminal(op->state);},30000,"KeepPosition current-cycle completion");
        const auto applied=engine.loopSpeedOperation(keepSpeed.id);const auto keepAfter=engine.getLoopSnapshot();const auto keepAfterDiagnostic=engine.getPlaybackDiagnostics();
        const bool keepContract=keepSpeed.result==Receipt::Accepted&&applied&&applied->committed&&applied->outputStarted&&applied->state==progressive::LoopSpeedState::Completed&&
            applied->cycle==0&&keepAfter.cycles==0&&!applied->fixedBoundary&&keepAfter.enabled&&keepAfter.id==keepReceipt.id&&
            keepAfter.inputGeneration==keepContext.inputGeneration&&keepAfter.startFrame==0&&keepAfter.endFrameExclusive==nextInfo.frames()&&engine.getPlaybackState()==State::Playing&&
            audit.frames.load()>keepFrames&&audit.affected.load()==keepAffected&&keepAfterDiagnostic.missingFrames==keepDiagnostic.missingFrames&&keepAfterDiagnostic.underrunCalls==keepDiagnostic.underrunCalls;
        ledger.row("KeepPosition_initial_current_cycle_application",keepContract?"PASS":"FAIL",
            ",\"contract\":\"same ordinary DSP applies before first B; independent PCM is a separate gate\""
            ",\"current_cycle_feature_validated\":true,\"defer_contract_only\":false,\"speed_request_id\":"+
            std::to_string(keepSpeed.id)+",\"accepted\":"+boolean(keepSpeed.result==Receipt::Accepted)+
            ",\"currentCycleSpeedChanges\":"+boolean(engine.loopAvailability().currentCycleSpeedChanges)+
            ",\"before\":"+keepBeforeSample+",\"after\":"+sample(engine,audit)+",\"independent_PCM\":\"NOT_RUN\"");
        engine.stop();
    }catch(const std::exception& exception){
        gate.release(); // the cleanup join must never wait for this test gate
        error=exception.what();
        ledger.row("execution_exception",setupComplete?"FAIL":"INCOMPLETE",",\"error\":"+quote(error));
        // A stuck stop/join is intentionally visible as missing SUMMARY or
        // external timeout. No timeout may be converted into a successful run.
        engine.stop();
    }
    const auto d=engine.getPlaybackDiagnostics();const auto n=engine.getNativeDiagnostics();
    const bool finalFinite=audit.nonfinite.load()==0;
    const auto finalOwners=phase58::RealtimePipeline::executionOwnerCounts();
    ledger.row("observed_output_finite_and_no_affected_frames",
        finalFinite&&!audit.affected.load()&&!gate.expired.load()&&finalOwners.alive==0&&finalOwners.peak<=2?"PASS":"FAIL",
        ",\"nonfinite_all_channels\":"+std::to_string(audit.nonfinite.load())+
        ",\"output_affected_or_padding\":"+std::to_string(audit.affected.load())+
        ",\"product_owners_alive_after_final_stop\":"+std::to_string(finalOwners.alive)+
        ",\"product_owners_peak\":"+std::to_string(finalOwners.peak)+
        ",\"worker_gate_expired\":"+boolean(gate.expired.load())+
        ",\"owner_measurement\":\"RealtimePipeline Impl construction-through-destruction global atomic counters\""+
        ",\"independent_PCM_comparison\":\"NOT_RUN\"");
    const bool completed=ledger.executed==8&&ledger.passed==8&&ledger.reproduced==0&&
        ledger.failed==0&&ledger.incomplete==0&&finalFinite&&!gate.expired.load()&&finalOwners.alive==0&&finalOwners.peak<=2;
    // Seven historical comparisons plus one actual KeepPosition application.
    // This host does not assert an independent DSP oracle.
    std::ostringstream summary;
    summary<<"{\"suite\":\"phase62_race_native_current\",\"investigation_basis_sha\":\"7c05319d8142ef53a70c95be4f214f293bb2428a\""
        <<",\"comparison_probe\":\"BaselineRaceProbe\",\"prototype\":\"Phase62RaceNative\""
        <<",\"expected\":8,\"baseline_comparison_cases\":7,\"additional_current_cycle_cases\":1,\"executed\":"<<ledger.executed<<",\"PASS\":"<<ledger.passed
        <<",\"REPRODUCED\":"<<ledger.reproduced<<",\"FAIL\":"<<ledger.failed<<",\"INCOMPLETE\":"<<ledger.incomplete
        <<",\"status\":"<<quote(ledger.failed?"FAIL":completed?"PASS":"INCOMPLETE")
        <<",\"nonfinite_all_channels\":"<<audit.nonfinite.load()<<",\"output_affected_or_padding\":"<<audit.affected.load()
        <<",\"product_owners_alive_after_final_stop\":"<<finalOwners.alive<<",\"product_owners_peak\":"<<finalOwners.peak
        <<",\"worker_gate\":\"SwitchPublished pre-offer\",\"worker_gate_expired\":"<<boolean(gate.expired.load())<<",\"callback_gate\":false"
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
        std::cout<<"{\"suite\":\"phase62_race_native_current\",\"expected\":8,\"executed\":0,\"status\":\"INCOMPLETE\",\"error\":"
            <<quote(error.what())<<",\"local_overall_go\":false}"<<std::endl;
    }});control.join();return result;
}
