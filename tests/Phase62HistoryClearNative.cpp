// A1: 公開APIのPaused Clear履歴不変性。各modeを別processで直列実行する。
// Merodoa 33ddcb6e の --audit-immutability と同じ14 checksを主試験とする。
// callbackは固定長カウンターと既存PCM監査だけ。待機・割当て・I/Oを追加しない。
#define PHASE62_PLAYING_LEDGER_NO_MAIN 1
#include "Phase62PlayingLedgerNative.cpp"
#include "playback/LoopSpeedLedger.h"

namespace {
std::vector<std::string> historyChecks(const std::string& mode){
    if(mode=="terminal_immutability")return {
        "M01.loop_allowed_manual_seek_disabled","M02.AB_100ms_accepted",
        "M03.actual_B_boundary_observed","M04.initial_duplicate_ID0",
        "M05.Pause_stops_cycles","M06.paused125_Accepted",
        "M07.ReadyForResume_without_PCM","M08.same_ID_Completed_frozen_before_Clear",
        "M09.Paused_Clear_accepted","M10.explicit_history_exact_Accepted_count",
        "M11.close_audit_owned_copy_all_joined","M12.close_operations_all_terminal",
        "M13.close_Accepted_ID_set_exact","M14.preClear_query_history_close_all_fields_immutable"};
    if(mode=="clear_continuation")return {
        "C01.past_Completed_frozen","C02.latest_unterminal_ReadyForResume",
        "C03.same_ID_Clear_transfer_before_old_join","C04.old_join_actual_discard_belongs_to_latest",
        "C05.C_cycles_and_PCM_stationary_before_Resume","C06.explicit_Resume_same_ID_actual_Completed",
        "C07.past_and_latest_terminal_all_fields_immutable","C08.close_owned_audit_exact_IDs_all_joined"};
    if(mode=="no_speed_clear")return {
        "N01.no_speed_Accepted_IDs","N02.Paused_Clear_actual_discard_Snapshot",
        "N03.C_cycles_and_PCM_stationary_before_Resume","N04.explicit_Resume_normal_supply",
        "N05.close_empty_owned_audit_all_joined"};
    if(mode=="terminal_states")return {
        "T01.Completed_all_fields_immutable","T02.Replaced_all_fields_immutable",
        "T03.Cancelled_all_fields_immutable","T04.Failed_all_fields_immutable",
        "T05.nonterminal_Clear_continuation_supplied_count","T06.ID_Loop_input_prepare_mismatch_rejected",
        "T07.noncontinuation_and_unknown_ID_rejected"};
    throw std::runtime_error("未知の履歴Clear試験modeです");
}

// セッション別のFIFO実消費総数。Diagnostics.consumedは周回内の座標に
// 戻るため、join済みpublishedとの差分にはこのRAW総数を使う。
struct HistoryCapture {
    struct Counter {std::atomic<std::uint64_t> session{0},frames{0};};
    NativeCapture native;
    std::array<Counter,64> counters{};
    explicit HistoryCapture(std::size_t channels):native(channels){}
    static void raw(void* pointer,const float*const* pcm,std::size_t count,std::size_t at,
                    std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& c=*static_cast<HistoryCapture*>(pointer);
        NativeCapture::raw(&c.native,pcm,count,at,generation,epoch,session);
        auto& slot=c.counters[session%c.counters.size()];
        if(slot.session.load(std::memory_order_relaxed)!=session){slot.frames.store(0,std::memory_order_relaxed);slot.session.store(session,std::memory_order_release);}
        slot.frames.fetch_add(count,std::memory_order_release);
    }
    static void output(void* pointer,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        NativeCapture::output(&static_cast<HistoryCapture*>(pointer)->native,pcm,span);
    }
    std::uint64_t consumed(std::uint64_t session)const noexcept{
        const auto& slot=counters[session%counters.size()];
        return slot.session.load(std::memory_order_acquire)==session?slot.frames.load(std::memory_order_acquire):0;
    }
};

struct HistoryFixture {
    std::filesystem::path folder;
    HistoryCapture capture;
    WorkerGate gate;
    FinalLedgerSink finalAudit; // sinkはengine破棄後にも所有コピーを保持する。
    std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
    std::vector<std::string> expected,passed;
    std::vector<std::uint64_t> ids;
    std::ofstream checks,receipts;
    std::uint64_t loopID=0;
    unsigned rate=0;
    HistoryFixture(const std::filesystem::path& input,Preset preset,const std::filesystem::path& out,
                   const std::vector<std::string>& wanted):folder(out),capture(ts::WavStreamReader(input).channels()),
                   expected(wanted),checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl"){
        ts::WavStreamReader wav(input);rate=wav.sampleRate();
        require(rate==48000&&wav.channels()==1&&wav.frames()==std::uint64_t(rate)*6,"代表条件は48kHz mono・6秒の人工入力です");
        ProgressiveOptions options;options.preset=preset;options.initialSpeed=1.;options.allowExperimentalLoops=true;
        options.allowUnvalidatedFastLocalSeek=false;options.callbackRecordLimit=8192;
        options.controlTestHooks={&gate,WorkerGate::event};
        options.observerContext=&capture;options.observeEpochPcm=HistoryCapture::raw;options.observeOutputPcm=HistoryCapture::output;
        options.finalLoopSpeedAuditContext=&finalAudit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},
            []()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew,std::memory_order_relaxed);callbackCounting=false;},
            []()noexcept{return callbackNew;}};
        require(engine->prepare(input,options),"通常prepare拒否");
        until([&]{return engine->getPlaybackState()==State::Ready;},"通常Ready期限");
    }
    ~HistoryFixture(){gate.released=true;if(engine)engine->stop();}
    void healthy(){
        require(!gate.expired,"通常workerの有限gate期限超過");
        require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"実行DSP所有者が2を超えた");
        if(engine&&engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);
    }
    template<class Predicate>void until(Predicate predicate,const char* reason){
        const auto end=Tick::now()+std::chrono::seconds(60);
        while(!predicate()){healthy();require(Tick::now()<end,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();
    }
    progressive::LoopContext context(){const auto s=engine->getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
    void pass(const char* id){
        require(passed.size()<expected.size()&&expected[passed.size()]==id,"check ID/順序不一致");passed.emplace_back(id);
        checks<<"{\"id\":"<<ph58::jsonString(id)<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"checks保存失敗");
    }
    void save(const char* name,const progressive::LoopSpeedOperation& op){std::ofstream out(folder/name);out<<operationJson(op)<<'\n';require(bool(out),"全フィールドの値保存失敗");}
    void saveHistory(const char* name){std::ofstream out(folder/name);for(const auto& op:engine->loopSpeedHistory())out<<operationJson(op)<<'\n';require(bool(out),"明示履歴保存失敗");}
    progressive::LoopSpeedOperation row(std::uint64_t id){const auto op=engine->loopSpeedOperation(id);require(op.has_value(),"公開個別照会にAccepted IDがない");return *op;}
    progressive::LoopSpeedReceipt request(double speed){
        const auto c=context();const auto r=engine->requestLoopSpeed(speed,c);
        receipts<<"{\"speed\":"<<speed<<",\"id\":"<<r.id<<",\"accepted\":"<<(r.accepted?"true":"false")
            <<",\"duplicate\":"<<(r.duplicate?"true":"false")<<",\"code\":"<<int(r.code)<<",\"reason\":"<<ph58::jsonString(r.reason)<<"}\n";
        receipts.flush();require(bool(receipts),"受付保存失敗");
        if(r.accepted&&!r.duplicate){require(r.id&&r.code==Code::Accepted,"新規Accepted ID不正");require(std::find(ids.begin(),ids.end(),r.id)==ids.end(),"Accepted ID重複");ids.push_back(r.id);}return r;
    }
    void beginLoop(bool recordMain){
        const auto r=engine->requestLoopRange(rate/2,rate/2+rate/10,context());require(r.accepted,"100ms AB受付拒否");loopID=r.id;
        if(recordMain)pass("M02.AB_100ms_accepted");
        until([&]{return engine->getLoopSnapshot().initialPositionComplete&&!engine->getPlaybackDiagnostics().retiringPipeline;},"初回ReturnToA完了期限");
        require(engine->getPlaybackState()==State::Ready&&engine->getCurrentPlaybackPosition().inputFrame==rate/2,"初回ReturnToAがReadyのAで静止しない");
        require(engine->play(),"Loop Play拒否");until([&]{return engine->getLoopSnapshot().cycles>=3;},"実周回期限");
        const auto l=engine->getLoopSnapshot();require(l.lastBoundary&&l.lastBoundary->inputA==rate/2&&l.lastBoundary->inputBExclusive==rate/2+rate/10,"実B境界が100ms ABに対応しない");
        if(recordMain)pass("M03.actual_B_boundary_observed");
    }
    void pauseStable(){
        require(engine->pause(),"Pause拒否");const auto cycles=engine->getLoopSnapshot().cycles;
        const auto frames=capture.native.frames.load();const auto position=engine->getCurrentPlaybackPosition().inputFrame;
        std::this_thread::sleep_for(std::chrono::milliseconds(300));healthy();
        require(engine->getPlaybackState()==State::Paused&&engine->getLoopSnapshot().cycles==cycles&&capture.native.frames.load()==frames&&engine->getCurrentPlaybackPosition().inputFrame==position,"Pause成功後にC/PCM/周回が進行");
    }
    progressive::LoopSpeedOperation ready(std::uint64_t id){
        until([&]{return row(id).state==LS::ReadyForResume&&!engine->getPlaybackDiagnostics().retiringPipeline;},"ReadyForResume期限");
        const auto op=row(id);require(!op.outputStarted&&!op.firstPcmObservedNs&&op.preparationVersion,"準備完了を実PCM適用と捏造した");return op;
    }
    progressive::LoopSpeedOperation completed(std::uint64_t id){
        until([&]{return progressive::terminal(row(id).state);},"同一ID終端期限");const auto op=row(id);
        require(op.id==id&&op.state==LS::Completed&&op.outputStarted&&op.firstPcmObservedNs&&op.session&&capture.consumed(op.session)>0&&!op.noChange,"同一IDの実PCM Completedがない");return op;
    }
    void clear(){const auto receipt=engine->requestClearLoop(loopID,context());require(receipt.accepted,"Paused Clear受付拒否");}
    void clearDone(){until([&]{const auto l=engine->getLoopSnapshot();return !l.enabled&&!l.clearPending&&!engine->getPlaybackDiagnostics().retiringPipeline;},"Clear完了/旧owner join期限");}
    std::uint64_t actualDiscard(std::uint64_t oldSession,std::uint64_t before){
        const auto l=engine->getLoopSnapshot();require(l.pausedClearDiscardedFrames>before,"Clear Snapshotの実破棄数が0");
        bool found=false;std::uint64_t actual=0;std::ofstream evidence(folder/"old_owner_actual_discard.json");
        for(const auto& epoch:engine->closedEpochs())if(epoch.pipeline.session==oldSession){
            require(!found&&epoch.pipeline.finalDataAvailable,"旧owner終了監査の重複またはjoin未完了");found=true;
            const auto& p=epoch.pipeline;const auto read=capture.consumed(oldSession);
            require(p.published>=p.outputStartFrame+read,"旧ownerの公開RAW総数と実FIFO消費数の順序不正");
            actual=p.published-p.outputStartFrame-read;
            evidence<<"{\"session\":"<<oldSession<<",\"render_epoch\":"<<epoch.renderEpoch<<",\"published\":"<<p.published
                <<",\"output_start\":"<<p.outputStartFrame<<",\"observer_RAW_consumed\":"<<read<<",\"actual_unconsumed_FIFO_frames\":"<<actual
                <<",\"Snapshot_discard_delta\":"<<l.pausedClearDiscardedFrames-before<<",\"final_data_available\":true,\"published_minus_logical_consumed_used\":false}\n";
        }
        require(found&&bool(evidence)&&actual>0&&actual==l.pausedClearDiscardedFrames-before,"旧ownerの実未消費FIFO数とClear Snapshot破棄数が不一致");return actual;
    }
    void stationary(std::optional<std::uint64_t> c,std::uint64_t frames,std::uint64_t cycles){
        require(c.has_value(),"停止位置Cが未測定");std::this_thread::sleep_for(std::chrono::milliseconds(150));healthy();
        const auto l=engine->getLoopSnapshot();require(engine->getPlaybackState()==State::Paused&&!engine->getStateSnapshot().resumePending&&engine->getCurrentPlaybackPosition().inputFrame==c&&capture.native.frames.load()==frames&&l.cycles==cycles&&l.pausedClearInputFrame==*c,"明示Resume前にC/PCM/周回が進んだ");
    }
    void beforeClose(){
        if(engine->getPlaybackState()==State::Playing)require(engine->pause(),"終了前Pause拒否");
        const auto d=engine->getPlaybackDiagnostics();const auto l=engine->getLoopSnapshot();const auto n=engine->getNativeDiagnostics();
        require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!l.failurePaddingFrames&&!l.outputAffectedFrames&&!l.safetyStopFrames,"通常供給に不足/書込拒否/失敗加工");
        require(d.callbackCppNew&&!*d.callbackCppNew&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback heap検出器不在または確保/解放あり");
        require(!capture.native.audit.errors&&!capture.native.audit.nonfinite,"RAW/境界補正/非有限値の監査失敗");
        require(engine->seekHistory().empty(),"内部処理が公開手動seek履歴に混入");
        writePhase62Trace(folder/"callbacks_all_spans.jsonl",engine->loopCallbackRecords());
        std::ofstream out(folder/"native_observation.json");out<<"{\"source_rate\":"<<rate<<",\"channels\":1,\"device_rate\":"<<n.deviceRate
            <<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"source_output_frames\":"<<capture.native.frames.load()<<",\"missing\":"<<d.missingFrames
            <<",\"callback_deadlines_observed\":"<<n.deadlineMisses<<",\"worker_deadlines_observed\":"<<d.workerDeadlineMisses
            <<",\"callback_gate\":false,\"RT_deadline_approval\":\"NOT_ASSESSED\",\"independent_DSP\":\"NOT_RUN\"}\n";require(bool(out),"実機観測保存失敗");
    }
    void close(){
        engine.reset();finalAudit.save(folder/"final_owned_audit.jsonl");
        require(finalAudit.complete(),"独立終了監査の配送/即時所有コピー/全join/退役未完了");
        const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"close後の実行DSP所有者残存/上限超過");
    }
    void auditIDs(){
        std::set<std::uint64_t> actual;for(const auto& op:finalAudit.operations){require(progressive::terminal(op.state),"終了監査に未終端ID");require(actual.insert(op.id).second,"終了監査ID重複");}
        require(actual==std::set<std::uint64_t>(ids.begin(),ids.end()),"終了監査とAccepted ID集合が不一致");
    }
    const progressive::LoopSpeedOperation& auditRow(std::uint64_t id)const{
        for(const auto& op:finalAudit.operations)if(op.id==id)return op;throw std::runtime_error("終了監査に比較対象IDがない");
    }
};

void terminalImmutability(HistoryFixture& f){
    require(f.engine->loopAvailability().allowed&&!f.engine->seekAvailability().interactiveAllowed,"Loop opt-inと手動seek無効が独立しない");f.pass("M01.loop_allowed_manual_seek_disabled");
    f.beginLoop(true);const auto duplicate=f.request(1.);
    require(duplicate.code==Code::DuplicateInitial&&duplicate.id==0&&duplicate.duplicate&&duplicate.accepted,"初期同値要求のID0契約違反");f.pass("M04.initial_duplicate_ID0");
    f.pauseStable();f.pass("M05.Pause_stops_cycles");const auto r=f.request(1.25);require(r.accepted&&!r.duplicate&&r.id,"Paused125受付拒否");f.pass("M06.paused125_Accepted");
    const auto prepared=f.ready(r.id);f.save("ready_for_resume.json",prepared);f.pass("M07.ReadyForResume_without_PCM");
    require(f.engine->resume(),"明示Resume拒否");f.save("same_ID_completed.json",f.completed(r.id));f.pauseStable();
    // Clear直前のネイティブ個別照会そのものを基準にする。
    const auto before=f.row(r.id);require(before.state==LS::Completed&&!before.clearContinuation,"Clear前Completedの状態/所属不正");
    const auto frozen=operationJson(before);f.save("terminal_before_Clear_query.json",before);f.pass("M08.same_ID_Completed_frozen_before_Clear");
    const auto oldSession=f.context().session;const auto discarded=f.engine->getLoopSnapshot().pausedClearDiscardedFrames;
    f.clear();f.pass("M09.Paused_Clear_accepted");f.clearDone();const auto actual=f.actualDiscard(oldSession,discarded);
    const auto after=f.row(r.id);f.save("terminal_after_Clear_query.json",after);f.saveHistory("after_Clear_history.jsonl");
    const auto history=f.engine->loopSpeedHistory();require(history.size()==f.ids.size()&&history.size()==1,"明示履歴とAccepted ID数が不一致");f.pass("M10.explicit_history_exact_Accepted_count");
    const bool explicitImmutable=frozen==operationJson(after),historyImmutable=frozen==operationJson(history.front());
    f.beforeClose();f.close();f.pass("M11.close_audit_owned_copy_all_joined");
    for(const auto& op:f.finalAudit.operations)require(progressive::terminal(op.state),"終了監査に未終端ID");f.pass("M12.close_operations_all_terminal");
    f.auditIDs();f.pass("M13.close_Accepted_ID_set_exact");
    const auto& final=f.auditRow(r.id);f.save("terminal_close_owned_copy.json",final);const bool finalImmutable=frozen==operationJson(final);
    std::ofstream comparison(f.folder/"immutability_comparison.json");comparison<<"{\"pre_Clear_source\":\"native_individual_query\",\"all_operation_fields_compared\":true,\"actual_old_FIFO_discard_frames\":"<<actual
        <<",\"terminalExplicitImmutable\":"<<(explicitImmutable?"true":"false")<<",\"terminalHistoryImmutable\":"<<(historyImmutable?"true":"false")
        <<",\"terminalFinalImmutable\":"<<(finalImmutable?"true":"false")<<",\"before\":"<<frozen<<",\"after_query\":"<<operationJson(after)
        <<",\"after_history\":"<<operationJson(history.front())<<",\"close_owned_copy\":"<<operationJson(final)<<"}\n";comparison.close();require(bool(comparison),"比較証拠保存失敗");
    require(explicitImmutable&&historyImmutable&&finalImmutable,"Paused Clearが既Completed行の全フィールド不変条件に違反");f.pass("M14.preClear_query_history_close_all_fields_immutable");
}

void continuation(HistoryFixture& f){
    f.beginLoop(false);f.pauseStable();const auto pastReceipt=f.request(.75);require(pastReceipt.accepted,"過去75受付拒否");f.ready(pastReceipt.id);
    require(f.engine->resume(),"過去75 Resume拒否");f.completed(pastReceipt.id);f.pauseStable();
    const auto past=f.row(pastReceipt.id);const auto pastJson=operationJson(past);f.save("past_Completed_before_latest.json",past);f.pass("C01.past_Completed_frozen");
    const auto latest=f.request(1.25);require(latest.accepted,"最新125受付拒否");const auto prepared=f.ready(latest.id);
    require(!progressive::terminal(prepared.state)&&!prepared.clearContinuation,"最新未終端準備の状態不正");f.save("latest_before_Clear.json",prepared);f.pass("C02.latest_unterminal_ReadyForResume");
    const auto oldContext=f.context();const auto c=f.engine->getCurrentPlaybackPosition().inputFrame;require(c.has_value(),"Clear継続の停止位置Cが未測定");
    const auto frames=f.capture.native.frames.load(),cycles=f.engine->getLoopSnapshot().cycles,discarded=f.engine->getLoopSnapshot().pausedClearDiscardedFrames;
    f.gate.arm(ProgressiveControlTestPoint::RetiringOld);f.clear();f.until([&]{return f.gate.entered.load();},"Clear旧owner退役前gate未到達");
    const auto transferred=f.row(latest.id);f.save("latest_Clear_before_old_join.json",transferred);
    require(transferred.id==latest.id&&transferred.loopID==f.loopID&&transferred.inputGeneration==oldContext.inputGeneration&&transferred.clearContinuation&&!progressive::terminal(transferred.state)&&transferred.state!=LS::ReadyForResume&&transferred.preparationVersion>prepared.preparationVersion&&!transferred.outputStarted&&!transferred.firstPcmObservedNs,"同一IDのClear移管/旧join前Ready非公開の契約違反");
    require(operationJson(f.row(past.id))==pastJson,"Clear移管が過去Completedを変更");f.pass("C03.same_ID_Clear_transfer_before_old_join");
    f.gate.released=true;f.until([&]{return f.gate.left.load();},"旧owner退役gate解放期限");f.clearDone();const auto actual=f.actualDiscard(oldContext.session,discarded);
    const auto ready=f.row(latest.id);f.save("latest_Clear_after_old_join.json",ready);
    require(ready.state==LS::ReadyForResume&&ready.clearContinuation&&ready.discardedForPausedClearFrames==actual&&ready.resumeInputFrame==*c&&ready.inputGeneration==oldContext.inputGeneration&&ready.preparationVersion==transferred.preparationVersion&&!ready.outputStarted&&!ready.firstPcmObservedNs&&operationJson(f.row(past.id))==pastJson,"実破棄数の最新ID所属/全join後Ready/過去不変が不一致");f.pass("C04.old_join_actual_discard_belongs_to_latest");
    f.stationary(c,frames,cycles);f.pass("C05.C_cycles_and_PCM_stationary_before_Resume");
    require(f.engine->resume(),"Clear明示Resume拒否");const auto final=f.completed(latest.id);
    require(final.clearContinuation&&final.discardedForPausedClearFrames==actual&&final.resumeInputFrame==*c,"同一Clear継続IDのCompletedが計数/Cを失った");
    f.save("latest_Clear_Completed.json",final);f.pass("C06.explicit_Resume_same_ID_actual_Completed");
    const auto finalJson=operationJson(final);f.pauseStable();require(operationJson(f.row(past.id))==pastJson&&operationJson(f.row(latest.id))==finalJson,"再開後に確定済み行が変更");
    f.saveHistory("after_Resume_history.jsonl");f.beforeClose();f.close();
    require(operationJson(f.auditRow(past.id))==pastJson&&operationJson(f.auditRow(latest.id))==finalJson,"closeが過去/最新終端全フィールドを変更");f.pass("C07.past_and_latest_terminal_all_fields_immutable");
    f.auditIDs();require(f.ids.size()==2,"Clear継続のAccepted ID数不正");f.pass("C08.close_owned_audit_exact_IDs_all_joined");
}

void noSpeed(HistoryFixture& f){
    f.beginLoop(false);f.pauseStable();require(f.ids.empty()&&f.engine->loopSpeedHistory().empty(),"速度要求なし試験に外部速度IDが混入");f.pass("N01.no_speed_Accepted_IDs");
    const auto old=f.context();const auto c=f.engine->getCurrentPlaybackPosition().inputFrame;
    const auto frames=f.capture.native.frames.load(),cycles=f.engine->getLoopSnapshot().cycles,discarded=f.engine->getLoopSnapshot().pausedClearDiscardedFrames;
    f.clear();f.clearDone();f.actualDiscard(old.session,discarded);require(f.engine->loopSpeedHistory().empty(),"速度要求なしClearが外部行を捏造");f.pass("N02.Paused_Clear_actual_discard_Snapshot");
    f.stationary(c,frames,cycles);f.pass("N03.C_cycles_and_PCM_stationary_before_Resume");
    require(f.engine->resume(),"速度要求なしClearの明示Resume拒否");f.until([&]{return f.capture.native.frames.load()>frames+2048;},"Clear後の通常PCM供給期限");
    require(!f.engine->getLoopSnapshot().enabled&&f.engine->getLoopSnapshot().cycles==cycles,"速度要求なしClear後に余分なLoop周回");f.pass("N04.explicit_Resume_normal_supply");
    f.beforeClose();f.close();f.auditIDs();require(f.finalAudit.operations.empty(),"速度要求なしcloseの外部ID捏造");f.pass("N05.close_empty_owned_audit_all_joined");
}

progressive::LoopSpeedOperation filledOperation(LS state){
    progressive::LoopSpeedOperation o;o.id=101;o.loopID=102;o.inputGeneration=103;o.sourceSession=104;o.sourceRenderEpoch=105;o.acceptedCycle=106;o.speedMicros=1250000;
    o.state=state;o.deferral=progressive::LoopSpeedDeferral::ProtectedFrontier;o.preparationVersion=107;o.dynamicOperationID=108;o.session=109;o.renderEpoch=110;
    o.producerCycle=111;o.cycle=112;o.mapVersion=113;o.outputEnd=114;o.dynamicSession=115;o.planningRenderEpoch=116;o.acceptedNs=117;o.preparingNs=118;o.readyNs=119;
    o.commitObservedNs=120;o.firstChangedPublishedObservedNs=121;o.firstPcmObservedNs=122;o.completedNs=123;o.terminalNs=124;o.firstChangedOutputFrame=125;
    o.completionOutputFrame=126;o.resumeInputFrame=127;o.discardedForPausedClearFrames=128;o.committed=true;o.outputStarted=true;o.fixedBoundary=true;
    o.adoptionPending=true;o.fixedBoundaryCommitted=true;o.noChange=true;o.clearContinuation=true;o.reason="全フィールド不変の局所検査";return o;
}
std::vector<std::string> localTerminalStates(const std::filesystem::path& folder,const std::vector<std::string>& expected){
    std::vector<std::string> passed;std::ofstream checks(folder/"checks.jsonl"),evidence(folder/"terminal_helper_values.jsonl");
    const auto pass=[&](const char* id){require(passed.size()<expected.size()&&expected[passed.size()]==id,"局所check順序不一致");passed.emplace_back(id);checks<<"{\"id\":"<<ph58::jsonString(id)<<",\"status\":\"PASS\"}\n";checks.flush();};
    for(const auto state:{LS::Completed,LS::Replaced,LS::Cancelled,LS::Failed}){
        progressive::LoopSpeedLedger ledger;const auto original=filledOperation(state);ledger.accept(original);const auto before=operationJson(original);
        const bool wrote=ledger.recordPausedClearDiscard(original.id,original.loopID,original.inputGeneration,original.preparationVersion,4197);
        require(!wrote&&operationJson(*ledger.find(original.id))==before,"製品Clear計数helperが終端行を書換え");
        ledger.replaceUnstarted(original.loopID,0,200);ledger.cancel(original.loopID,201,"局所取消");ledger.cancelUnstarted(original.loopID,202,"局所未開始取消");ledger.retireEpoch(original.session,true,203);
        require(operationJson(*ledger.find(original.id))==before,"近接台帳処理が確定行を変更");
        evidence<<"{\"state\":"<<ph58::jsonString(progressive::name(state))<<",\"write_accepted\":false,\"before\":"<<before<<",\"after\":"<<operationJson(*ledger.find(original.id))<<"}\n";
        pass(state==LS::Completed?"T01.Completed_all_fields_immutable":state==LS::Replaced?"T02.Replaced_all_fields_immutable":state==LS::Cancelled?"T03.Cancelled_all_fields_immutable":"T04.Failed_all_fields_immutable");
    }
    progressive::LoopSpeedLedger ledger;auto op=filledOperation(LS::Preparing);op.committed=op.outputStarted=op.fixedBoundaryCommitted=op.adoptionPending=false;ledger.accept(op);
    require(ledger.recordPausedClearDiscard(op.id,op.loopID,op.inputGeneration,op.preparationVersion,4197),"正当な未終端Clear継続へ計数できない");
    auto wanted=op;wanted.discardedForPausedClearFrames=4197;require(operationJson(*ledger.find(op.id))==operationJson(wanted),"Clear継続計数が他フィールドを変更");pass("T05.nonterminal_Clear_continuation_supplied_count");
    const auto stable=operationJson(*ledger.find(op.id));
    require(!ledger.recordPausedClearDiscard(op.id+1,op.loopID,op.inputGeneration,op.preparationVersion,99)&&
        !ledger.recordPausedClearDiscard(op.id,op.loopID+1,op.inputGeneration,op.preparationVersion,99)&&
        !ledger.recordPausedClearDiscard(op.id,op.loopID,op.inputGeneration+1,op.preparationVersion,99)&&
        !ledger.recordPausedClearDiscard(op.id,op.loopID,op.inputGeneration,op.preparationVersion+1,99)&&operationJson(*ledger.find(op.id))==stable,"ID/Loop/入力/prepare不一致を受理");pass("T06.ID_Loop_input_prepare_mismatch_rejected");
    ledger.find(op.id)->clearContinuation=false;const auto nonclear=operationJson(*ledger.find(op.id));
    require(!ledger.recordPausedClearDiscard(op.id,op.loopID,op.inputGeneration,op.preparationVersion,99)&&
        !ledger.recordPausedClearDiscard(0,op.loopID,op.inputGeneration,op.preparationVersion,99)&&operationJson(*ledger.find(op.id))==nonclear,"Clear非移管/未知IDを計数対象にした");pass("T07.noncontinuation_and_unknown_ID_rejected");
    evidence<<"{\"nonterminal_after_valid_count\":"<<stable<<",\"mismatch_preserves_all_fields\":true,\"noncontinuation_preserves_all_fields\":true}\n";
    require(bool(checks)&&bool(evidence),"局所試験証拠保存失敗");return passed;
}
}

int main(int argc,char** argv){
    if(argc!=6){std::cerr<<"MODE INPUT baseline|candidate NEW_OUTPUT_DIR SOURCE_LIST_SHA256\n";return 2;}
    int result=1;std::thread owner([&]{std::filesystem::path folder;bool owned=false;std::unique_ptr<HistoryFixture> f;
        const std::string mode=argv[1],preset=argv[3];std::vector<std::string> expected,passed;
        try{
            expected=historyChecks(mode);require(preset=="baseline"||preset=="candidate","preset不正");
            const std::string sourceSha=argv[5];require(sourceSha.size()==64&&sourceSha.find_first_not_of("0123456789abcdef")==std::string::npos,"ソース一覧SHA-256不正");
            folder=std::filesystem::absolute(argv[4]);require(std::filesystem::create_directories(folder),"既存証拠出力先へ上書きしない");owned=true;
            std::ofstream manifest(folder/"EXPECTED.json");manifest<<"{\"schema\":1,\"suite\":\"phase62_history_Clear\",\"mode\":"<<ph58::jsonString(mode)
                <<",\"preset\":"<<ph58::jsonString(preset)<<",\"expected\":"<<expected.size()<<",\"expected_Accepted_external_ID_count\":"<<(mode=="terminal_immutability"?1:mode=="clear_continuation"?2:0)
                <<",\"source_list_sha256\":"<<ph58::jsonString(sourceSha)<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))
                <<",\"input_sha256\":"<<ph58::jsonString(fileHash(argv[2]))<<",\"driver_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::path(__FILE__)))
                <<",\"source_rate\":48000,\"channels\":1,\"input_seconds\":6,\"A_frame\":24000,\"B_frame_exclusive\":28800,\"initial_speed\":1,\"callback_gate\":false,\"all_operation_fields_compared\":true,\"expected_IDs\":[";
            for(std::size_t i=0;i<expected.size();++i)manifest<<(i?",":"")<<ph58::jsonString(expected[i]);manifest<<"],\"Merodoa_reference_commit\":\"33ddcb6e3dafcb4f5f408a465b726824bf9f5005\",\"Merodoa_14check_mapping\":\"M01..M14 correspond in original check order\",\"independent_DSP\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";manifest.close();require(bool(manifest),"EXPECTED保存失敗");
            if(mode=="terminal_states")passed=localTerminalStates(folder,expected);
            else{
                phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;
                void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();
                require(phase61_heap_allocations()&&phase61_heap_frees(),"heap検出器の自己試験失敗");phase61_heap_reset();hostCallbackCppNew=0;
                f=std::make_unique<HistoryFixture>(argv[2],preset=="baseline"?Preset::Baseline:Preset::Candidate,folder,expected);
                if(mode=="terminal_immutability")terminalImmutability(*f);else if(mode=="clear_continuation")continuation(*f);else noSpeed(*f);passed=f->passed;
            }
            require(passed==expected,"必須check集合または件数不一致");std::ofstream summary(folder/"SUMMARY.json");
            summary<<"{\"schema\":1,\"mode\":"<<ph58::jsonString(mode)<<",\"run_complete\":true,\"status\":\"PASS\",\"expected\":"<<expected.size()<<",\"executed\":"<<passed.size()<<",\"Accepted_IDs\":[";
            if(f)for(std::size_t i=0;i<f->ids.size();++i)summary<<(i?",":"")<<f->ids[i];summary<<"],\"callback_gate\":false,\"independent_DSP\":\"NOT_RUN\",\"local_overall_go\":false}\n";summary.close();require(bool(summary),"SUMMARY保存失敗");std::ifstream saved(folder/"SUMMARY.json");std::cout<<saved.rdbuf();result=0;
        }catch(const std::exception& error){
            std::cerr<<error.what()<<'\n';if(f){f->gate.released=true;try{if(f->engine){f->saveHistory("failure_history.jsonl");f->engine.reset();}f->finalAudit.save(folder/"failure_owned_audit.jsonl");}catch(...){}}
            if(owned){std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"mode\":"<<ph58::jsonString(mode)<<",\"run_complete\":false,\"status\":\"FAIL\",\"expected\":"<<expected.size()<<",\"executed\":"<<(f?f->passed.size():passed.size())<<",\"reason\":"<<ph58::jsonString(error.what())<<"}\n";}
        }
    });owner.join();return result;
}
