// 公開APIによるPlaying台帳・競合試験。実施結果は独立したrun manifestで管理。
// One mode per process. Public playback/ledger APIs and normal-worker hooks only.
#define main includedPhase62NativeMain
#include "Phase62NativeTests.cpp"
#undef main
#include "prototype/Phase45PcmDigest.h"
#include <optional>
#include <set>
#include <sstream>

namespace {
namespace ph58=ts::prototype::phase58;
using LS=progressive::LoopSpeedState;
using Code=progressive::LoopSpeedReceiptCode;
using Tick=std::chrono::steady_clock;
std::atomic<std::uint64_t> hostCallbackCppNew{0};

std::string fileHash(const std::filesystem::path& path){
    std::ifstream file(path,std::ios::binary);require(bool(file),"hash input missing");ts::prototype::Phase45PcmDigest digest;std::array<char,65536> block{};
    while(file.read(block.data(),block.size())||file.gcount())digest.update(block.data(),std::size_t(file.gcount()));require(file.eof(),"hash read failed");return digest.finish();
}
std::string operationJson(const progressive::LoopSpeedOperation& o){
    std::ostringstream s;s<<"{\"id\":"<<o.id<<",\"loop_id\":"<<o.loopID<<",\"input_generation\":"<<o.inputGeneration<<",\"source_session\":"<<o.sourceSession<<",\"source_epoch\":"<<o.sourceRenderEpoch
        <<",\"accepted_cycle\":"<<o.acceptedCycle<<",\"speed_micros\":"<<o.speedMicros<<",\"state\":"<<ph58::jsonString(progressive::name(o.state))<<",\"deferral\":"<<int(o.deferral)
        <<",\"preparation_version\":"<<o.preparationVersion<<",\"dynamic_operation_id\":"<<o.dynamicOperationID<<",\"dynamic_session\":"<<o.dynamicSession<<",\"planning_epoch\":"<<o.planningRenderEpoch
        <<",\"session\":"<<o.session<<",\"render_epoch\":"<<o.renderEpoch<<",\"producer_cycle\":"<<o.producerCycle<<",\"loop_cycle\":"<<o.cycle<<",\"map_version\":"<<o.mapVersion<<",\"output_end\":"<<o.outputEnd
        <<",\"accepted_ns\":"<<o.acceptedNs<<",\"preparing_ns\":"<<o.preparingNs<<",\"ready_ns\":"<<o.readyNs<<",\"commit_observed_ns\":"<<o.commitObservedNs<<",\"first_changed_published_observed_ns\":"<<o.firstChangedPublishedObservedNs
        <<",\"first_PCM_observed_ns\":"<<o.firstPcmObservedNs<<",\"completed_ns\":"<<o.completedNs<<",\"terminal_ns\":"<<o.terminalNs<<",\"first_changed_output\":"<<o.firstChangedOutputFrame<<",\"completion_output\":"<<o.completionOutputFrame
        <<",\"resume_input_frame\":"<<o.resumeInputFrame<<",\"discarded_for_paused_clear_frames\":"<<o.discardedForPausedClearFrames
        <<",\"committed\":"<<(o.committed?"true":"false")<<",\"output_started\":"<<(o.outputStarted?"true":"false")<<",\"fixed_boundary\":"<<(o.fixedBoundary?"true":"false")<<",\"fixed_boundary_committed\":"<<(o.fixedBoundaryCommitted?"true":"false")
        <<",\"clear_continuation\":"<<(o.clearContinuation?"true":"false")<<",\"adoption_pending\":"<<(o.adoptionPending?"true":"false")<<",\"no_change\":"<<(o.noChange?"true":"false")<<",\"reason\":"<<ph58::jsonString(o.reason)<<'}';return s.str();
}
struct WorkerGate {
    std::atomic<ProgressiveControlTestPoint> point{ProgressiveControlTestPoint::SwitchPublished};
    std::atomic<bool> armed{false},entered{false},released{false},left{false},expired{false},cleanupWait{false};
    void arm(ProgressiveControlTestPoint p){require(!entered.load()||left.load(),"rearm before previous hook returned");point=p;entered=false;released=false;left=false;cleanupWait=false;armed=true;}
    static void event(void* context,ProgressiveControlTestPoint p)noexcept{
        auto& g=*static_cast<WorkerGate*>(context);if(p==ProgressiveControlTestPoint::SeekCleanupWait)g.cleanupWait=true;
        if(p!=g.point.load()||!g.armed.exchange(false))return;g.entered=true;const auto end=Tick::now()+std::chrono::seconds(45);
        while(!g.released.load()&&Tick::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));if(!g.released.load())g.expired=true;g.left=true;
    }
};
// Engine破棄後にも値を所有する通常側sink。spanやEngineへの参照は保持しない。
struct FinalLedgerSink {
    static constexpr std::size_t maximumOperations=4096;
    std::vector<progressive::LoopSpeedOperation> operations;
    std::uint64_t calls=0,sequence=0;
    bool received=false,workersJoined=false,retirementComplete=false;
    bool duplicateDelivery=false,oversized=false,copyFailed=false,invalidMarker=false;
    FinalLedgerSink(){operations.reserve(maximumOperations);}
    static bool receive(void* context,const FinalLoopSpeedAudit& audit)noexcept{
        auto& sink=*static_cast<FinalLedgerSink*>(context);
        if(++sink.calls!=1){sink.duplicateDelivery=true;return false;}
        sink.sequence=audit.sequence;sink.workersJoined=audit.workersJoined;sink.retirementComplete=audit.retirementComplete;
        if(!audit.sequence||!audit.workersJoined||!audit.retirementComplete){sink.invalidMarker=true;return false;}
        if(audit.operations.size()>maximumOperations||audit.operations.size()>sink.operations.capacity()){sink.oversized=true;return false;}
        try{sink.operations.assign(audit.operations.begin(),audit.operations.end());}
        catch(...){sink.copyFailed=true;return false;}
        sink.received=true;return true;
    }
    bool complete()const noexcept{return received&&calls==1&&sequence&&workersJoined&&retirementComplete&&!duplicateDelivery&&!oversized&&!copyFailed&&!invalidMarker;}
    void save(const std::filesystem::path& path)const{
        std::ofstream file(path);require(bool(file),"final sink evidence open failed");
        file<<"{\"record\":\"audit_delivery\",\"calls\":"<<calls<<",\"sequence\":"<<sequence<<",\"received\":"<<(received?"true":"false")
            <<",\"workers_joined\":"<<(workersJoined?"true":"false")<<",\"retirement_complete\":"<<(retirementComplete?"true":"false")
            <<",\"duplicate_delivery\":"<<(duplicateDelivery?"true":"false")<<",\"oversized\":"<<(oversized?"true":"false")
            <<",\"copy_failed\":"<<(copyFailed?"true":"false")<<",\"invalid_marker\":"<<(invalidMarker?"true":"false")<<",\"copied_count\":"<<operations.size()<<"}\n";
        for(const auto& op:operations)file<<operationJson(op)<<'\n';
        file.flush();require(bool(file),"final sink evidence write failed");
    }
};
struct RawStamp {std::uint64_t generation=0,session=0,epoch=0;std::size_t firstAt=0,end=0;};
struct NativeCapture {
    LoopPcmAudit audit;
    std::array<RawStamp,64> writing{};
    std::array<ts::prototype::phase59::ValueMailbox<RawStamp>,64> observed;
    std::atomic<std::uint64_t> frames{0},naturalBs{0};
    explicit NativeCapture(std::size_t channels):audit(channels){}
    static void raw(void* context,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& c=*static_cast<NativeCapture*>(context);LoopPcmAudit::source(&c.audit,pcm,n,at,generation,epoch,session);auto& stamp=c.writing[epoch%64];
        if(stamp.epoch!=epoch)stamp={generation,session,epoch,at,at+n};else stamp.end=at+n;c.observed[epoch%64].publish(stamp);
    }
    static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& c=*static_cast<NativeCapture*>(context);LoopPcmAudit::output(&c.audit,pcm,span);c.frames.fetch_add(span.frames,std::memory_order_relaxed);
        if(span.periodicBoundary&&span.periodOffset+span.frames==span.periodFrames)c.naturalBs.fetch_add(1,std::memory_order_relaxed);
    }
};
struct LedgerFixture {
    WorkerGate gate;
    std::vector<std::unique_ptr<NativeCapture>> captures;
    ProgressiveOptions options;
    FinalLedgerSink finalAudit; // engineより先に構築し、後に破棄する。
    std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
    const std::filesystem::path folder;
    std::ofstream checks,receipts;
    std::vector<std::string> expectedChecks,passedChecks;
    std::vector<std::uint64_t> ids;
    std::uint64_t loopID=0,b=0;
    std::size_t initialSeeks=0;
    unsigned rate=0;
    LedgerFixture(const std::filesystem::path& input,Preset preset,const std::filesystem::path& out,std::vector<std::string> expected,std::size_t limit,ph58::ControlTestHooks pipelineHooks={},std::chrono::milliseconds prepareTimeout=std::chrono::milliseconds(120000),ProgressiveControlTestHooks engineHooks={}):folder(out),checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl"),expectedChecks(std::move(expected)){
        ts::WavStreamReader wav(input);rate=wav.sampleRate();b=std::uint64_t(rate)*8;require(wav.frames()>=std::uint64_t(rate)*9,"needs >=9s input; native Loop is [0,8s)");
        options.pipelineControlTestHooks=pipelineHooks;options.prepareTimeout=prepareTimeout;
        options.preset=preset;options.initialSpeed=1;options.allowExperimentalLoops=true;options.callbackRecordLimit=4096;options.loopSpeedOperationLimitForTest=limit;
        options.finalLoopSpeedAuditContext=&finalAudit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
        options.controlTestHooks=engineHooks.event?engineHooks:ProgressiveControlTestHooks{&gate,WorkerGate::event};options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew,std::memory_order_relaxed);callbackCounting=false;},[]()noexcept{return callbackNew;}};
        prepare(input);const auto receipt=engine->requestLoopRange(0,b,context());require(receipt.accepted,"initial ReturnToA rejected");loopID=receipt.id;
        until([&]{return engine->getLoopSnapshot().initialPositionComplete&&!engine->getPlaybackDiagnostics().retiringPipeline;},"initial Loop Ready/retirement");initialSeeks=engine->seekHistory().size();
        require(engine->play(),"initial play");firstPcm(*engine);until([&]{return capture().frames.load()>=rate/5;},"initial audio");
    }
    ~LedgerFixture(){gate.released=true;if(engine)engine->stop();}
    NativeCapture& capture(){return *captures.back();}
    progressive::LoopContext context(){const auto s=engine->getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
    void prepare(const std::filesystem::path& input){
        const ts::WavStreamReader wav(input);captures.push_back(std::make_unique<NativeCapture>(wav.channels()));options.observerContext=&capture();options.observeEpochPcm=NativeCapture::raw;options.observeOutputPcm=NativeCapture::output;
        require(engine->prepare(input,options),"prepare rejected");until([&]{return engine->getPlaybackState()==State::Ready;},"normal Ready");
    }
    void healthy(){require(!gate.expired,"normal-worker gate expired");if(engine&&engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"third execution owner");}
    template<class P> void until(P predicate,const char* why){const auto end=Tick::now()+std::chrono::seconds(60);while(!predicate()){healthy();require(Tick::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();}
    void releaseGate(){gate.released=true;until([&]{return gate.left.load();},"normal-worker hook release");}
    void pass(const char* id){require(passedChecks.size()<expectedChecks.size()&&expectedChecks[passedChecks.size()]==id,"check ID/order mismatch");passedChecks.push_back(id);checks<<"{\"id\":"<<ph58::jsonString(id)<<",\"status\":\"PASS\"}\n";checks.flush();}
    void recordReceipt(const char* name,double speed,const progressive::LoopSpeedReceipt& r,progressive::LoopContext c){
        receipts<<"{\"call\":"<<ph58::jsonString(name)<<",\"speed\":"<<speed<<",\"id\":"<<r.id<<",\"accepted\":"<<(r.accepted?"true":"false")<<",\"duplicate\":"<<(r.duplicate?"true":"false")<<",\"code\":"<<int(r.code)<<",\"generation\":"<<c.inputGeneration<<",\"session\":"<<c.session<<",\"epoch\":"<<c.renderEpoch<<",\"reason\":"<<ph58::jsonString(r.reason)<<"}\n";receipts.flush();
    }
    progressive::LoopSpeedReceipt request(const char* name,double speed){
        const auto c=context();const auto r=engine->requestLoopSpeed(speed,c);recordReceipt(name,speed,r,c);
        require(r.accepted&&!r.duplicate&&r.id&&r.code==Code::Accepted,"expected a new Accepted external ID");require(std::find(ids.begin(),ids.end(),r.id)==ids.end(),"duplicate fresh ID");ids.push_back(r.id);return r;
    }
    progressive::LoopSpeedOperation row(std::uint64_t id){const auto value=engine->loopSpeedOperation(id);require(value.has_value(),"Accepted ID absent from public ledger");return *value;}
    void saveLedger(const char* name){std::ofstream f(folder/name);for(const auto& o:engine->loopSpeedHistory())f<<operationJson(o)<<'\n';}
    void exactIds(bool allTerminal){const auto history=engine->loopSpeedHistory();std::set<std::uint64_t> expected(ids.begin(),ids.end()),actual;for(const auto& o:history){require(actual.insert(o.id).second,"duplicate ledger ID");if(allTerminal)require(progressive::terminal(o.state),"Accepted ID left nonterminal");}require(expected==actual,"missing/foreign Accepted ledger ID");}
    void completed(std::uint64_t id){until([&]{return progressive::terminal(row(id).state);},"request terminal deadline");require(row(id).state==LS::Completed,"request ended without Completed");}
    progressive::LoopSpeedOperation commit75(){
        const auto receipt=request("75",.75);until([&]{return row(receipt.id).committed;},"75 dynamic commit");const auto op=row(receipt.id);const auto loop=engine->getLoopSnapshot();
        require(!op.fixedBoundaryCommitted&&op.dynamicOperationID&&op.dynamicSession&&op.mapVersion&&op.outputEnd&&loop.cycles==0&&loop.dynamicCycle==0,"75 was not current-cycle dynamic commit");
        require(engine->getPlaybackDiagnostics().currentEpochPresentedFrame+4096<op.outputEnd,"commit observation too late for B-before replacement fixture");return op;
    }
    void required75Boundary(const progressive::LoopSpeedOperation& committed){
        until([&]{return gate.entered.load();},"next preparation did not enter normal hook after required B");const auto loop=engine->getLoopSnapshot();const auto s=engine->getStateSnapshot();const auto events=engine->loopHistory();
        require(loop.cycles==1&&events.size()==1&&events[0].oldOutputEnd==committed.outputEnd&&events[0].callbackFrame==committed.outputEnd&&!events[0].overlapFrames,"required dynamic B coordinate/cycle changed");
        require(loop.appliedSpeed==.75&&s.appliedTargetSpeed==.75,"required fixed75 boundary owner missing/mislabeled");
        until([&]{const auto event=capture().observed[events[0].newEpoch%64].read();return event&&event->epoch==events[0].newEpoch&&event->firstAt==0&&event->end>0;},"required fixed75 A PCM not observed");
        const auto frames=capture().frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(80));healthy();require(capture().frames.load()>frames&&engine->getLoopSnapshot().cycles==1,"valid fixed75 supply stopped while normal worker delayed");
        const auto old=row(committed.id);require(old.committed&&old.state!=LS::Replaced,"committed past rewritten Replaced");
    }
    void stopWhileGated(){
        require(gate.entered&&!gate.left,"Stop fixture hook not held");std::atomic<bool> observed{false};
        std::thread release([&]{const auto end=Tick::now()+std::chrono::seconds(5);while(!gate.cleanupWait.load()&&Tick::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));observed=gate.cleanupWait.load();gate.released=true;});
        engine->stop();release.join();require(observed,"Stop did not reach seek cleanup before normal gate release");
    }
    void qualityAndOwnership(){
        if(engine){if(engine->getPlaybackState()==State::Playing)require(engine->pause(),"final pause");const auto d=engine->getPlaybackDiagnostics();const auto loop=engine->getLoopSnapshot();
            require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!loop.failurePaddingFrames&&!loop.outputAffectedFrames,"unexpected missing/padding/rejected PCM");
            require(d.callbackCppNew&&!*d.callbackCppNew,"callback C++new detector absent or nonzero");if(captures.size()==1)require(engine->seekHistory().size()==initialSeeks,"internal work fabricated a user seek");
            const auto n=engine->getNativeDiagnostics();std::ofstream observed(folder/"native_observation.json");observed<<"{\"source_rate\":"<<d.sourceSampleRate<<",\"channels\":"<<d.channels<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"missing\":"<<d.missingFrames<<",\"underrun_calls\":"<<d.underrunCalls<<",\"rejected_writes\":"<<d.rejectedWrites<<",\"padding\":"<<loop.failurePaddingFrames<<",\"callback_deadlines_observed\":"<<n.deadlineMisses<<",\"worker_deadlines_observed\":"<<d.workerDeadlineMisses<<",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"observer_stage\":\"pre-mainMixer\"}\n";engine->stop();
            for(const auto& epoch:engine->closedEpochs())require(epoch.pipeline.finalDataAvailable,"unjoined epoch");
            writePhase62Trace(folder/"callbacks_all_spans.jsonl",engine->loopCallbackRecords());writePhase62Trace(folder/"clock_anomaly_window.jsonl",engine->loopClockAnomalyRecords());
        }
        for(const auto& c:captures)require(!c->audit.errors&&!c->audit.nonfinite,"product RAW/boundary arithmetic failure");
        require(!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback new/malloc/free");const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"owner leak/peak");
    }
};

std::vector<std::string> checksFor(const std::string& mode){
    if(mode=="latest_noop")return {"75_cancelled_before_commit","100_completed_noop","40_replaced_before_commit","200_completed_actual_PCM","all_four_IDs_terminal","normal_supply_and_owner_cap"};
    if(mode=="committed_replace")return {"75_committed_before_B","200_accepted_without_rewriting_75","required_fixed75_B_and_PCM","75_and_200_completed","past_immutable_all_IDs_terminal","normal_supply_and_owner_cap"};
    if(mode=="committed_clear")return {"75_committed_before_B","100_transferred_to_Clear_before_B","Clear_rejects_speed_with_reason","required_fixed75_B_and_PCM","Clear_normal_continuation_no_extra_cycle","latest100_Clear_PCM_all_IDs_terminal_past_immutable","normal_supply_and_owner_cap"};
    if(mode=="limit_stop"||mode=="limit_reprepare"||mode=="limit_close")return {"three_Accepted_IDs_reserved","limit_rejection_preserves_latest_and_PCM","duplicate_keeps_ID_at_limit",mode=="limit_stop"?"Stop_cancels_all_IDs":mode=="limit_reprepare"?"Stop_then_different_input_no_stale_revival":"direct_close_quiesces_and_retires",mode=="limit_close"?"post_close_owned_sink_exact_IDs_and_terminal_kinds":"all_IDs_terminal_history_immutable","normal_supply_and_owner_cap"};
    throw std::runtime_error("unknown mode");
}
void latestNoop(LedgerFixture& f){
    f.gate.arm(ProgressiveControlTestPoint::SwitchPublished);const auto old=f.request("75_uncommitted",.75);f.until([&]{return f.gate.entered.load();},"75 pre-offer hook");require(!f.row(old.id).committed,"75 committed before pre-offer gate");
    const auto same=f.request("100_cancel_to_current",1.0);f.releaseGate();f.until([&]{return progressive::terminal(f.row(old.id).state);},"75 replacement terminal");require(f.row(old.id).state==LS::Replaced&&!f.row(old.id).committed,"75 unexpectedly applied");f.pass("75_cancelled_before_commit");
    f.completed(same.id);require(f.row(same.id).noChange&&!f.row(same.id).committed&&f.engine->getStateSnapshot().appliedTargetSpeed==1.,"100 did not complete as actual NoOp");f.pass("100_completed_noop");
    f.gate.arm(ProgressiveControlTestPoint::SwitchPublished);const auto forty=f.request("40_uncommitted",.4);f.until([&]{return f.gate.entered.load();},"40 pre-offer hook");const auto latest=f.request("200_latest",2.0);f.releaseGate();
    f.until([&]{return progressive::terminal(f.row(forty.id).state);},"40 replacement terminal");require(f.row(forty.id).state==LS::Replaced&&!f.row(forty.id).committed,"40 was not replaced before commit");f.pass("40_replaced_before_commit");
    f.completed(latest.id);const auto applied=f.row(latest.id);require(applied.outputStarted&&!applied.noChange&&applied.session&&applied.renderEpoch&&applied.firstPcmObservedNs&&f.engine->getStateSnapshot().appliedTargetSpeed==2.,"200 Completed lacks actual PCM identity");f.pass("200_completed_actual_PCM");
    require(f.ids.size()==4,"external request count");f.exactIds(true);f.saveLedger("terminal_ledger.jsonl");f.pass("all_four_IDs_terminal");f.qualityAndOwnership();f.pass("normal_supply_and_owner_cap");
}
void committed(LedgerFixture& f,bool clear){
    const auto old=f.commit75();f.pass("75_committed_before_B");f.gate.arm(ProgressiveControlTestPoint::SeekPreparationStarted);const auto latest=f.request(clear?"100_pending_before_Clear":"200_after_commit",clear?1.0:2.0);
    require(f.row(old.id).committed&&f.row(old.id).state!=LS::Replaced&&f.engine->getLoopSnapshot().cycles==0,"old required version lost before B");
    if(clear){const auto receipt=f.engine->requestClearLoop(f.loopID,f.context());require(receipt.accepted&&!f.engine->getLoopSnapshot().enabled&&f.engine->getLoopSnapshot().clearPending,"Clear admission");
        const auto transferred=f.row(latest.id);require(!progressive::terminal(transferred.state)&&!transferred.noChange&&!transferred.committed,"latest100 was cancelled or falsely completed while retained for Clear");f.pass("100_transferred_to_Clear_before_B");
        const auto c=f.context();const auto rejected=f.engine->requestLoopSpeed(.4,c);f.recordReceipt("Clear_pending_rejection",.4,rejected,c);require(!rejected.accepted&&!rejected.reason.empty()&&rejected.code==Code::ClearPending,"Clear pending speed silently accepted/lost");f.pass("Clear_rejects_speed_with_reason");
    }else f.pass("200_accepted_without_rewriting_75");
    f.required75Boundary(old);f.pass("required_fixed75_B_and_PCM");f.releaseGate();
    if(clear){f.until([&]{return !f.engine->getLoopSnapshot().clearPending;},"Clear completion deadline");require(f.engine->getPlaybackState()==State::Playing,"Clear did not continue audio");require(f.engine->pause(),"Clear final pause");
        const auto l=f.engine->getLoopSnapshot();require(!l.enabled&&!l.clearPending&&!f.engine->getPlaybackDiagnostics().pipeline.loopReuse.enabled&&l.cycles==f.capture().naturalBs.load(),"Clear revived Loop or counted connection as cycle");f.pass("Clear_normal_continuation_no_extra_cycle");
        f.completed(old.id);const auto past=operationJson(f.row(old.id));f.completed(latest.id);const auto applied=f.row(latest.id);const auto normal=f.engine->getPlaybackDiagnostics();
        require(applied.speedMicros==1000000&&applied.outputStarted&&applied.firstPcmObservedNs&&!applied.noChange&&applied.session==normal.session&&applied.renderEpoch==normal.renderEpoch&&f.engine->getStateSnapshot().appliedTargetSpeed==1.,"latest100 did not complete in the actual Clear continuation epoch");
        std::ofstream transfer(f.folder/"clear_transfer.json");transfer<<"{\"required_committed75_ID\":"<<old.id<<",\"transferred_latest100_ID\":"<<latest.id<<",\"application_scope\":\"ExplicitClearContinuation\",\"normal_session\":"<<normal.session<<",\"normal_epoch\":"<<normal.renderEpoch<<",\"normal_output_start\":"<<normal.pipeline.outputStartFrame<<",\"latest100_completed_by_actual_PCM\":true}\n";transfer.close();
        f.exactIds(true);f.engine->stop();require(operationJson(f.row(old.id))==past,"completed75 changed at Stop");f.saveLedger("terminal_ledger.jsonl");f.pass("latest100_Clear_PCM_all_IDs_terminal_past_immutable");
    }else{f.completed(old.id);const auto past=operationJson(f.row(old.id));f.completed(latest.id);require(f.row(latest.id).outputStarted&&f.engine->getStateSnapshot().appliedTargetSpeed==2.,"200 actual application missing");f.pass("75_and_200_completed");f.exactIds(true);f.engine->stop();require(operationJson(f.row(old.id))==past,"completed75 changed after replacement/Stop");f.saveLedger("terminal_ledger.jsonl");f.pass("past_immutable_all_IDs_terminal");}
    require(f.ids.size()==2&&f.engine->seekHistory().size()==f.initialSeeks,"request count or fabricated seek");f.qualityAndOwnership();f.pass("normal_supply_and_owner_cap");
}
bool limited(LedgerFixture& f,const std::string& mode,const std::filesystem::path& other){
    std::optional<progressive::LoopSpeedOperation> completedBeforeClose;
    if(mode=="limit_close"){
        const auto past=f.request("75_completed_before_direct_close",.75);f.completed(past.id);
        const auto applied=f.row(past.id);require(applied.committed&&applied.outputStarted&&applied.firstPcmObservedNs&&applied.completedNs&&applied.dynamicSession&&applied.dynamicOperationID&&!applied.noChange,"close fixture lacks a real Completed PCM operation");
        // このCompleted IDを含む旧ownerのB引継ぎ・退役まで済ませる。
        // 直接close自体の前にはStopを呼ばず、安定した固定75の実PCMを維持する。
        f.until([&]{const auto d=f.engine->getPlaybackDiagnostics();return d.session!=applied.dynamicSession&&!d.retiringPipeline&&f.engine->getLoopSnapshot().appliedSpeed==.75;},"completed75 B handoff and retirement before direct close");
        completedBeforeClose=f.row(past.id);require(completedBeforeClose->state==LS::Completed&&completedBeforeClose->outputStarted,"completed75 changed before close fixture");
        f.gate.arm(ProgressiveControlTestPoint::SwitchPublished);f.request("125_uncommitted_before_direct_close",1.25);f.until([&]{return f.gate.entered.load();},"close fixture pre-offer hook");
    }else{
        f.gate.arm(ProgressiveControlTestPoint::SwitchPublished);f.request("75_uncommitted",.75);f.until([&]{return f.gate.entered.load();},"limit fixture pre-offer hook");f.request("125_replacement",1.25);
    }
    const auto newest=f.request("150_latest",1.5);require(f.ids.size()==3,"limit fixture Accepted count");f.exactIds(false);f.pass("three_Accepted_IDs_reserved");
    const auto before=f.engine->getStateSnapshot();const auto loop=f.engine->getLoopSnapshot();const auto stale=f.context();const auto frames=f.capture().frames.load();const auto refusalContext=f.context();const auto rejected=f.engine->requestLoopSpeed(2.,refusalContext);f.recordReceipt("limit_rejection",2.,rejected,refusalContext);
    require(!rejected.accepted&&!rejected.id&&!rejected.reason.empty()&&rejected.code==Code::LimitReached,"external limit rejection/reason");const auto after=f.engine->getStateSnapshot();
    require(after.requestedSpeed==before.requestedSpeed&&after.resumePending==before.resumePending&&f.engine->getLoopSnapshot().speedRequestID==newest.id&&f.engine->getLoopSnapshot().id==loop.id&&f.engine->loopSpeedHistory().size()==3,"limit refusal changed latest/intention/loop");
    std::this_thread::sleep_for(std::chrono::milliseconds(80));f.healthy();require(f.capture().frames.load()>frames&&f.engine->getPlaybackState()==State::Playing,"valid PCM stopped at admission cap");f.pass("limit_rejection_preserves_latest_and_PCM");
    const auto duplicateContext=f.context();const auto duplicate=f.engine->requestLoopSpeed(1.5,duplicateContext);f.recordReceipt("duplicate_at_limit",1.5,duplicate,duplicateContext);require(duplicate.accepted&&duplicate.duplicate&&duplicate.id==newest.id&&duplicate.code==Code::Duplicate&&f.engine->loopSpeedHistory().size()==3,"duplicate consumed slot or changed latest ID");f.pass("duplicate_keeps_ID_at_limit");
    if(mode=="limit_close"){
        const auto d=f.engine->getPlaybackDiagnostics();const auto l=f.engine->getLoopSnapshot();require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!l.failurePaddingFrames&&!l.outputAffectedFrames,"pre-close supply failure");
        require(f.engine->seekHistory().size()==f.initialSeeks,"internal work fabricated a user seek before close");
        const auto beforeClose=f.engine->loopSpeedHistory();require(completedBeforeClose.has_value()&&beforeClose.size()==3,"close fixture missing completed past or Accepted rows");
        const auto replaced=f.row(f.ids[1]);require(replaced.state==LS::Replaced&&!replaced.committed&&!replaced.outputStarted&&!replaced.reason.empty(),"close fixture middle ID was not replaced before adoption");
        const auto latestBeforeClose=f.row(newest.id);require(!progressive::terminal(latestBeforeClose.state)&&!latestBeforeClose.committed&&!latestBeforeClose.outputStarted,"close fixture latest ID was already adopted/terminal");
        f.saveLedger("pre_close_ledger.jsonl");require(!f.finalAudit.calls,"final audit delivered before destruction");
        std::atomic<bool> closeStarted{false};std::thread release([&]{while(!closeStarted.load())std::this_thread::yield();std::this_thread::sleep_for(std::chrono::milliseconds(60));f.gate.released=true;});
        closeStarted=true;f.engine.reset();release.join();
        // 以後Engineへアクセスしない。破棄より長寿命のsinkと音声観測だけを使う。
        f.finalAudit.save(f.folder/"sink.jsonl");f.healthy();
        const auto held=f.capture().frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(100));f.healthy();
        require(f.capture().frames.load()==held&&!ph58::RealtimePipeline::executionOwnerCounts().alive,"close leaked owner or revived old PCM");f.pass("direct_close_quiesces_and_retires");
        require(f.finalAudit.complete()&&f.finalAudit.operations.size()==f.ids.size(),"final audit absent, duplicated, incomplete, oversized, or failed to copy");
        std::set<std::uint64_t> accepted(f.ids.begin(),f.ids.end()),actual;
        require(accepted.size()==f.ids.size(),"Accepted receipt set contains duplicate IDs");
        for(const auto& final:f.finalAudit.operations){
            require(actual.insert(final.id).second&&accepted.count(final.id)&&progressive::terminal(final.state),"final sink contains duplicate, foreign, or nonterminal Accepted ID");
            const auto prior=std::find_if(beforeClose.begin(),beforeClose.end(),[&](const auto& op){return op.id==final.id;});
            require(prior!=beforeClose.end()&&final.loopID==prior->loopID&&final.inputGeneration==prior->inputGeneration&&final.sourceSession==prior->sourceSession&&final.sourceRenderEpoch==prior->sourceRenderEpoch&&final.acceptedNs==prior->acceptedNs&&final.speedMicros==prior->speedMicros,"final sink lost Accepted identity/context");
            require(final.terminalNs>=final.acceptedNs&&final.terminalNs,"final sink terminal marker absent");
            if(progressive::terminal(prior->state))require(operationJson(final)==operationJson(*prior),"direct close rewrote a previously terminal operation or its PCM/start facts");
            if(final.id==completedBeforeClose->id)require(final.state==LS::Completed&&operationJson(final)==operationJson(*completedBeforeClose)&&final.committed&&final.outputStarted&&final.firstPcmObservedNs&&final.completedNs,"direct close lost Completed past or actual PCM/start facts");
            else if(final.id==replaced.id)require(final.state==LS::Replaced&&!final.committed&&!final.outputStarted&&!final.reason.empty(),"direct close changed unadopted replacement terminal kind");
            else require(final.id==newest.id&&final.state==LS::Cancelled&&!final.committed&&!final.outputStarted&&!final.firstPcmObservedNs&&!final.reason.empty(),"direct close latest uncommitted ID was not reasoned Cancelled");
        }
        require(actual==accepted,"final sink is missing an Accepted receipt ID");
        {std::ofstream marker(f.folder/"sink.jsonl",std::ios::app);require(bool(marker),"final sink marker open failed");marker<<"{\"record\":\"FINAL_LOOP_SPEED_AUDIT_COMPLETE\",\"sequence\":"<<f.finalAudit.sequence<<",\"expected_Accepted\":"<<accepted.size()<<",\"actual\":"<<actual.size()<<",\"Completed\":1,\"Replaced\":1,\"Cancelled\":1,\"all_workers_joined\":true,\"retirement_complete\":true,\"receipt_ID_set_exact\":true,\"past_immutable\":true,\"direct_close\":true}\n";marker.flush();require(bool(marker),"final sink marker write failed");}
        f.pass("post_close_owned_sink_exact_IDs_and_terminal_kinds");f.qualityAndOwnership();f.pass("normal_supply_and_owner_cap");return true;
    }
    f.stopWhileGated();f.exactIds(true);f.saveLedger("after_stop_ledger.jsonl");std::vector<std::string> history;for(auto id:f.ids)history.push_back(operationJson(f.row(id)));
    if(mode=="limit_reprepare"){
        f.prepare(other);const auto current=f.context();require(current.inputGeneration!=stale.inputGeneration&&!f.engine->getLoopSnapshot().enabled&&!f.engine->getLoopSnapshot().clearPending&&!f.engine->getStateSnapshot().resumePending,"old state revived on new input");
        const auto denied=f.engine->requestLoopSpeed(.75,stale);f.recordReceipt("old_input_context",.75,denied,stale);require(!denied.accepted&&!denied.reason.empty()&&denied.code==Code::StaleContext,"old input context accepted");require(f.engine->play(),"new input play");firstPcm(*f.engine);const auto started=f.capture().frames.load();f.until([&]{return f.capture().frames.load()>started+512;},"new input PCM");require(!f.engine->getLoopSnapshot().enabled,"old Loop revived on new input play");f.engine->stop();f.pass("Stop_then_different_input_no_stale_revival");
    }else{const auto held=f.capture().frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(100));require(f.capture().frames.load()==held&&!f.engine->getLoopSnapshot().enabled,"Stop revived audio/loop");f.pass("Stop_cancels_all_IDs");}
    f.exactIds(true);for(std::size_t i=0;i<f.ids.size();++i)require(operationJson(f.row(f.ids[i]))==history[i],"old terminal ledger history changed");f.saveLedger("terminal_ledger.jsonl");f.pass("all_IDs_terminal_history_immutable");f.qualityAndOwnership();f.pass("normal_supply_and_owner_cap");return true;
}
}

#ifndef PHASE62_PLAYING_LEDGER_NO_MAIN
int main(int argc,char** argv){
    if(argc<5||argc>6){std::cerr<<"MODE INPUT candidate|baseline NEW_OUTPUT_DIR [DIFFERENT_INPUT_FOR_REPREPARE]\n";return 2;}
    int exitCode=1;std::thread owner([&]{std::filesystem::path folder;bool owned=false;std::unique_ptr<LedgerFixture> fixture;std::string mode=argv[1];try{
        const auto input=std::filesystem::absolute(argv[2]);const std::string presetName=argv[3];require(presetName=="candidate"||presetName=="baseline","preset");const auto expected=checksFor(mode);const auto limit=mode.rfind("limit_",0)==0?3u:4096u;
        const auto other=argc==6?std::filesystem::absolute(argv[5]):std::filesystem::path{};if(mode=="limit_reprepare")require(!other.empty()&&fileHash(input)!=fileHash(other),"reprepare requires a different-content input");
        folder=std::filesystem::absolute(argv[4]);require(std::filesystem::create_directories(folder),"new output directory required");owned=true;
        std::ofstream manifest(folder/"EXPECTED.json");manifest<<"{\"schema\":1,\"suite\":\"phase62_playing_ledger\",\"mode\":"<<ph58::jsonString(mode)<<",\"preset\":"<<ph58::jsonString(presetName)<<",\"expected\":"<<expected.size()<<",\"expected_IDs\":[";
        for(std::size_t i=0;i<expected.size();++i)manifest<<(i?",":"")<<ph58::jsonString(expected[i]);manifest<<"],\"expected_Accepted_receipts\":"<<(mode=="latest_noop"?4:mode.rfind("limit_",0)==0?3:2)<<",\"admission_limit\":"<<limit<<",\"input_sha256\":"<<ph58::jsonString(fileHash(input))<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))<<",\"other_input_sha256\":"<<ph58::jsonString(other.empty()?"":fileHash(other))<<",\"worker_gate_only\":true,\"callback_gate\":false,\"independent_DSP\":\"NOT_RUN\",\"E_full_coverage\":false}\n";manifest.close();
        phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"heap detector self-test");phase61_heap_reset();
        fixture=std::make_unique<LedgerFixture>(input,presetName=="candidate"?Preset::Candidate:Preset::Baseline,folder,expected,limit);bool complete=true;
        if(mode=="latest_noop")latestNoop(*fixture);else if(mode=="committed_replace"||mode=="committed_clear")committed(*fixture,mode=="committed_clear");else complete=limited(*fixture,mode,other);
        const auto observed=fixture->passedChecks.size();const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(!complete||observed==expected.size(),"final check count mismatch");
        std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"run_complete\":true,\"suite\":\"phase62_playing_ledger\",\"mode\":"<<ph58::jsonString(mode)<<",\"expected\":"<<expected.size()<<",\"executed\":"<<observed<<",\"Accepted_IDs\":[";for(std::size_t i=0;i<fixture->ids.size();++i)summary<<(i?",":"")<<fixture->ids[i];
        summary<<"],\"status\":"<<ph58::jsonString(complete?"PASS":"INCOMPLETE")<<",\"owner_peak\":"<<owners.peak<<",\"owners_alive\":"<<owners.alive<<",\"callback_CPP_new\":"<<hostCallbackCppNew.load()<<",\"callback_malloc\":"<<phase61_heap_allocations()<<",\"callback_free\":"<<phase61_heap_frees()<<",\"independent_DSP\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"physical_loopback\":\"NOT_RUN\",\"E_full_coverage\":false}\n";summary.close();std::ifstream result(folder/"SUMMARY.json");std::cout<<result.rdbuf();exitCode=complete?0:3;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';if(fixture){fixture->gate.released=true;if(fixture->engine)fixture->engine->stop();if(fixture->engine)fixture->saveLedger("failure_ledger.jsonl");}if(owned){std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"run_complete\":false,\"suite\":\"phase62_playing_ledger\",\"mode\":"<<ph58::jsonString(mode)<<",\"expected\":"<<checksFor(mode).size()<<",\"executed\":"<<(fixture?fixture->passedChecks.size():0)<<",\"status\":\"FAIL\",\"reason\":"<<ph58::jsonString(e.what())<<"}\n";}}});owner.join();return exitCode;
}

#endif
