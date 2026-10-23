// Clear待ちから新しいReturnToAを直接要求する公開API host。
// Engine実装をincludeせず、callbackを止めず、通常workerだけを有限gateする。
#define PHASE62_PLAYING_LEDGER_NO_MAIN 1
#include "Phase62PlayingLedgerNative.cpp"
#include <map>

namespace {
struct ReenableCapture {
    struct Count {std::atomic<std::uint64_t> session{0},frames{0};};
    NativeCapture native;std::array<Count,64> counts{};
    std::atomic<std::uint64_t> baseline{0},firstOther{0},missingOrAffected{0};
    explicit ReenableCapture(std::size_t channels):native(channels){}
    static void raw(void* p,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& c=*static_cast<ReenableCapture*>(p);NativeCapture::raw(&c.native,pcm,n,at,generation,epoch,session);
        auto& slot=c.counts[session%c.counts.size()];if(slot.session.load()!=session){slot.frames=0;slot.session=session;}slot.frames.fetch_add(n,std::memory_order_release);
        if(n&&c.baseline.load()&&session!=c.baseline.load()){std::uint64_t empty=0;c.firstOther.compare_exchange_strong(empty,session,std::memory_order_release);}
    }
    static void output(void* p,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{auto& c=*static_cast<ReenableCapture*>(p);NativeCapture::output(&c.native,pcm,span);c.missingOrAffected.fetch_add(span.oldMissingFrames+span.newMissingFrames+span.outputAffectedFrames+span.failurePaddingFrames,std::memory_order_relaxed);}
    std::uint64_t frames(std::uint64_t session)const noexcept{const auto& slot=counts[session%counts.size()];return slot.session.load(std::memory_order_acquire)==session?slot.frames.load(std::memory_order_acquire):0;}
};
struct ReenableHooks {
    WorkerGate dispatch,stage,followup;
    std::atomic<bool> partialStopDecision{false};
    static void event(void* p,ProgressiveControlTestPoint point)noexcept{
        auto& h=*static_cast<ReenableHooks*>(p);
        if(point==ProgressiveControlTestPoint::PartialMixStopDecision){h.partialStopDecision=true;return;}
        // 一つのeventを次段gateへ二重に使用しない。
        if(h.dispatch.armed.load()&&h.dispatch.point.load()==point){WorkerGate::event(&h.dispatch,point);return;}
        if(h.stage.armed.load()&&h.stage.point.load()==point){WorkerGate::event(&h.stage,point);return;}
        WorkerGate::event(&h.followup,point);
    }
    void release()noexcept{dispatch.released=true;stage.released=true;followup.released=true;}
    bool expired()const noexcept{return dispatch.expired||stage.expired||followup.expired;}
};
bool interrupted(const std::string& mode){return mode=="latest_stop"||mode=="latest_reprepare"||mode=="latest_close";}
bool retainedInterrupted(const std::string& mode){return mode=="retained_stop"||mode=="retained_close";}
std::vector<std::string> reenableChecks(const std::string& mode){
    require(mode=="preparing"||mode=="requested"||mode=="started_done"||mode=="paused_preparing"||mode=="paused_adopted"||interrupted(mode)||retainedInterrupted(mode),"未知の再ON mode");
    if(retainedInterrupted(mode))return {"R01.past_Completed_39fields_frozen","R02.Clear_same_ID_requested_window","R03.new_Loop_fresh_context_accepted","RI04.retained_Clear_actual_PCM_before_action","RI05.action_quiesced_joined_no_new_Loop","RI06.adopted_Clear_terminal_not_Replaced","RI07.past_39fields_supply_heap_caps","RI08.close_owned_exact_IDs_all_joined"};
    std::vector<std::string> ids={"R01.past_Completed_39fields_frozen","R02.Clear_same_ID_requested_window","R03.new_Loop_fresh_context_accepted","R04.old_Clear_cancel_or_started_identity"};
    if(interrupted(mode)){
        ids.insert(ids.end(),{"R05.new_Loop_preparing_then_action","R06.no_stale_revival_past_immutable","R07.callback_supply_heap_and_owner_caps","R08.close_owned_copy_exact_IDs_all_joined"});
    }else ids.insert(ids.end(),{"R05.new_ReturnToA_and_explicit_play_intent","R06.past_and_terminal_39fields_immutable","R07.A_then_natural_B_without_stale_Clear","R08.exact_Accepted_IDs_terminal","R09.callback_supply_heap_and_owner_caps","R10.close_owned_copy_exact_IDs_all_joined"});
    return ids;
}
double msSince(Tick::time_point from){return std::chrono::duration<double,std::milli>(Tick::now()-from).count();}
struct ReenableFixture {
    const std::filesystem::path input,folder;ReenableCapture capture;ReenableHooks hooks;FinalLedgerSink audit;
    std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
    ProgressiveOptions options;std::vector<std::string> expected,passed;std::vector<std::uint64_t> ids;
    std::map<std::uint64_t,std::string> frozen;std::ofstream checks,receipts;unsigned rate=0;
    std::uint64_t loopID=0,clearSpeedID=0,pastID=0,newLoopID=0,oldSession=0;
    std::set<std::uint64_t> closedBefore;Tick::time_point clearAt{},requestAt{};
    double clearReceiptMs=0,newReceiptMs=0,oldRetiredMs=-1,newInitialMs=-1;
    bool clearAdopted=false,clearPcm=false;std::uint64_t clearSession=0;
    std::optional<std::uint64_t> clearC;std::uint64_t pausedClearFrames=0;
    ReenableFixture(const std::filesystem::path& path,Preset preset,const std::filesystem::path& out,std::vector<std::string> wanted)
        :input(path),folder(out),capture(ts::WavStreamReader(path).channels()),expected(std::move(wanted)),checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl"){
        ts::WavStreamReader wav(path);rate=wav.sampleRate();require(wav.frames()>=std::uint64_t(rate)*6,"6秒以上の入力が必要");
        options.preset=preset;options.initialSpeed=1.;options.allowExperimentalLoops=true;options.allowUnvalidatedFastLocalSeek=false;options.callbackRecordLimit=8192;
        options.controlTestHooks={&hooks,ReenableHooks::event};options.observerContext=&capture;options.observeEpochPcm=ReenableCapture::raw;options.observeOutputPcm=ReenableCapture::output;
        options.finalLoopSpeedAuditContext=&audit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew);callbackCounting=false;},[]()noexcept{return callbackNew;}};
        require(engine->prepare(path,options),"通常prepare拒否");until([&]{return engine->getPlaybackState()==State::Ready;},"通常Ready期限");
    }
    ~ReenableFixture(){hooks.release();if(engine)engine->stop();}
    void healthy(){require(!hooks.expired(),"通常worker有限gate期限超過");require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"実行DSP ownerが2を超過");if(engine&&engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);}
    template<class P>void until(P predicate,const char* why){const auto end=Tick::now()+std::chrono::seconds(60);while(!predicate()){healthy();require(Tick::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();}
    progressive::LoopContext context(){const auto s=engine->getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
    progressive::LoopSpeedOperation row(std::uint64_t id){const auto op=engine->loopSpeedOperation(id);require(op.has_value(),"Accepted外部IDの個別値がない");return *op;}
    void pass(const char* id){require(passed.size()<expected.size()&&expected[passed.size()]==id,"check順序/集合不一致");passed.emplace_back(id);checks<<"{\"id\":"<<ph58::jsonString(id)<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"check保存失敗");}
    void saveRow(const char* name,std::uint64_t id){std::ofstream out(folder/name);out<<operationJson(row(id))<<'\n';require(bool(out),"個別全fields保存失敗");}
    void saveHistory(const char* name){std::ofstream out(folder/name);for(const auto& op:engine->loopSpeedHistory())out<<operationJson(op)<<'\n';require(bool(out),"履歴保存失敗");}
    progressive::LoopSpeedReceipt speed(double value){const auto c=context();const auto r=engine->requestLoopSpeed(value,c);
        receipts<<"{\"call\":\"speed\",\"speed\":"<<value<<",\"id\":"<<r.id<<",\"accepted\":"<<(r.accepted?"true":"false")<<",\"duplicate\":"<<(r.duplicate?"true":"false")<<",\"code\":"<<int(r.code)<<",\"reason\":"<<ph58::jsonString(r.reason)<<"}\n";receipts.flush();
        require(r.accepted&&!r.duplicate&&r.id&&std::find(ids.begin(),ids.end(),r.id)==ids.end(),"新規速度ID受付失敗/重複");ids.push_back(r.id);return r;}
    void release(WorkerGate& gate){gate.released=true;until([&]{return gate.left.load();},"通常gate解放期限");}
    void pause(){require(engine->pause(),"Pause拒否");const auto frames=capture.native.frames.load(),cycles=engine->getLoopSnapshot().cycles;const auto c=engine->getCurrentPlaybackPosition().inputFrame;
        std::this_thread::sleep_for(std::chrono::milliseconds(80));healthy();require(c.has_value()&&capture.native.frames.load()==frames&&engine->getLoopSnapshot().cycles==cycles&&engine->getCurrentPlaybackPosition().inputFrame==c,"Pause後にC/PCM/周回が進行");}
    void ready(std::uint64_t id){until([&]{return row(id).state==LS::ReadyForResume&&!engine->getPlaybackDiagnostics().retiringPipeline;},"停止中Ready/旧owner退役期限");require(!row(id).outputStarted&&!row(id).firstPcmObservedNs,"Readyを実適用と偽記録");}
    void terminalFreeze(){for(const auto& op:engine->loopSpeedHistory())if(progressive::terminal(op.state)){const auto value=operationJson(op);auto [it,added]=frozen.emplace(op.id,value);require(added||it->second==value,"終端全39fieldsが事後変更");}}
    void pastUnchanged(){require(operationJson(row(pastID))==frozen.at(pastID),"確定済み過去Completedの39fields変更");terminalFreeze();}
    void initial(){const auto r=engine->requestLoopRange(rate/2,rate/2+rate,context());require(r.accepted,"初期1秒AB拒否");loopID=r.id;
        until([&]{return engine->getLoopSnapshot().initialPositionComplete&&!engine->getPlaybackDiagnostics().retiringPipeline;},"初期ReturnToA期限");require(engine->play(),"初期Play拒否");until([&]{return engine->getLoopSnapshot().cycles>=1;},"初期実B未観測");
        pause();pastID=speed(.75).id;ready(pastID);require(engine->resume(),"過去75のResume拒否");until([&]{return row(pastID).state==LS::Completed;},"過去75 Completed期限");
        const auto op=row(pastID);require(op.outputStarted&&op.firstPcmObservedNs&&capture.frames(op.session)>0,"過去75の実PCMがない");terminalFreeze();saveRow("past_Completed_before_Clear.json",pastID);pass("R01.past_Completed_39fields_frozen");
    }
    void enterClear(const std::string& mode){
        const bool paused=mode.rfind("paused_",0)==0;
        if(paused){pause();clearSpeedID=speed(1.25).id;ready(clearSpeedID);}
        else{
            hooks.dispatch.arm(ProgressiveControlTestPoint::LoopJobDispatch);clearSpeedID=speed(1.25).id;
            until([&]{return hooks.dispatch.entered.load();},"Clear移管前のdispatch gate期限");
            require(row(clearSpeedID).state==LS::Pending,"dispatch前の125がPendingでない");
        }
        oldSession=context().session;capture.baseline=oldSession;capture.firstOther=0;for(const auto& e:engine->closedEpochs())closedBefore.insert(e.pipeline.session);
        if(paused){clearC=engine->getCurrentPlaybackPosition().inputFrame;pausedClearFrames=capture.native.frames.load();require(clearC.has_value(),"Paused ClearのCが未取得");}
        hooks.stage.arm(mode=="requested"?ProgressiveControlTestPoint::SwitchPublished:mode=="started_done"?ProgressiveControlTestPoint::SwitchStartedOrDone:mode=="paused_adopted"?ProgressiveControlTestPoint::RetiringOld:ProgressiveControlTestPoint::SeekPreparationStarted);
        clearAt=Tick::now();const auto c=context();const auto receipt=engine->requestClearLoop(loopID,c);clearReceiptMs=msSince(clearAt);require(receipt.accepted,"Clear受付拒否");
        if(!paused)release(hooks.dispatch);
        until([&]{return hooks.stage.entered.load();},"指定Clear段階の通常gate期限");
        const auto transferred=row(clearSpeedID);require(transferred.clearContinuation&&!progressive::terminal(transferred.state)&&engine->getLoopSnapshot().clearPending,"Clearの同一ID移管/指定段階を確認できない");
        if(paused)require(engine->getCurrentPlaybackPosition().inputFrame==clearC&&capture.native.frames.load()==pausedClearFrames,"Paused Clear指定窓までにC/PCM進行");
        if(mode=="started_done")until([&]{return capture.firstOther.load()!=0;},"開始済みClearの実RAW未観測");
        saveRow("Clear_at_gate.json",clearSpeedID);pastUnchanged();pass("R02.Clear_same_ID_requested_window");
    }
    void newRange(){const auto c=context();
        if(row(clearSpeedID).outputStarted){progressive::LoopOptions keep;keep.startPolicy=progressive::LoopStartPolicy::KeepPosition;
            const auto rejected=engine->requestLoopRange(0,ts::WavStreamReader(input).frames(),c,keep);
            require(!rejected.accepted&&!rejected.reason.empty()&&engine->getLoopSnapshot().clearPending,"旧owner退役中のKeepPositionを誤ったownerへ接続");}
        requestAt=Tick::now();const auto r=engine->requestLoopRange(rate/4,rate/4+rate/2,c);newReceiptMs=msSince(requestAt);
        receipts<<"{\"call\":\"new_range\",\"id\":"<<r.id<<",\"old_loop_id\":"<<loopID<<",\"accepted\":"<<(r.accepted?"true":"false")<<",\"generation\":"<<c.inputGeneration<<",\"session\":"<<c.session<<",\"epoch\":"<<c.renderEpoch<<",\"reason\":"<<ph58::jsonString(r.reason)<<"}\n";receipts.flush();
        require(r.accepted&&r.id&&r.id!=loopID,"新鮮contextの再ON拒否/Loop ID再利用");newLoopID=r.id;const auto l=engine->getLoopSnapshot();require(l.id==r.id&&l.enabled&&!l.clearPending&&l.startFrame==rate/4&&l.endFrameExclusive==rate/4+rate/2,"最新Loop希望が一件として公開されない");
        if(clearC)require(engine->getCurrentPlaybackPosition().inputFrame==clearC&&capture.native.frames.load()==pausedClearFrames,"再ON受付時に停止C/PCMを変更");
        saveRow("Clear_after_reenable_receipt.json",clearSpeedID);terminalFreeze();pass("R03.new_Loop_fresh_context_accepted");}
    void characterizeClear(const std::string& mode){
        const auto finalSession=context().session;std::ofstream out(folder/"Clear_owner_outcome.jsonl");bool found=false;
        for(const auto& epoch:engine->closedEpochs())if(!closedBefore.count(epoch.pipeline.session)&&epoch.pipeline.session!=oldSession&&epoch.pipeline.session!=finalSession){
            require(!found&&epoch.pipeline.finalDataAvailable,"Clear準備ownerが重複/未join");found=true;clearSession=epoch.pipeline.session;clearPcm=capture.frames(clearSession)>0;clearAdopted=!epoch.preparedOnly;
            require(!epoch.preparedOnly||!clearPcm,"取消した未採用ClearがRAWを消費");
            out<<"{\"session\":"<<clearSession<<",\"epoch\":"<<epoch.renderEpoch<<",\"prepared_only\":"<<(epoch.preparedOnly?"true":"false")<<",\"RAW_received_frames\":"<<capture.frames(clearSession)<<",\"final_data_available\":true}\n";
        }
        require(found&&bool(out),"Clear準備ownerを公開終了監査から識別できない");oldRetiredMs=msSince(requestAt);
        const bool paused=mode.rfind("paused_",0)==0;const auto op=row(clearSpeedID);
        if(mode=="preparing"||mode=="paused_preparing"||interrupted(mode))require(!clearAdopted&&!clearPcm,"未採用Clearを取消せず使用した");
        if(mode=="started_done")require(clearAdopted&&clearPcm,"Started/DoneのClear採用と実PCMを失った");
        if(mode=="paused_adopted")require(clearAdopted&&!clearPcm,"Paused採用済みClearが未採用扱い/自動消費");
        if(clearPcm&&!paused)require(op.state==LS::Completed&&op.outputStarted&&op.firstPcmObservedNs&&op.session==clearSession,"Started勝ちの移管速度IDをCompleted前に取消した/実PCM identity喪失");
        else require(op.state==LS::Cancelled&&!op.reason.empty()&&!op.firstPcmObservedNs&&!op.outputStarted,"未出力Clear移管IDの取消/未消費契約違反");
        saveRow("Clear_final_operation.json",clearSpeedID);terminalFreeze();pass("R04.old_Clear_cancel_or_started_identity");
    }
    void quality(){
        if(engine&&engine->getPlaybackState()==State::Playing)require(engine->pause(),"監査前Pause拒否");
        if(engine){const auto d=engine->getPlaybackDiagnostics();const auto l=engine->getLoopSnapshot();
            require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!l.safetyStopFrames&&!l.failurePaddingFrames&&!l.outputAffectedFrames,"PCM不足/拒否/安全停止");
            require(d.pipeline.loopReuse.checkpointPeak<=2,"不変checkpointが2枠を超過");
            require(d.callbackCppNew&&!*d.callbackCppNew,"callback C++new検出器不在/確保あり");
            writePhase62Trace(folder/"callbacks_all_spans.jsonl",engine->loopCallbackRecords());
            std::ofstream epochs(folder/"closed_epochs.jsonl");for(const auto& e:engine->closedEpochs()){require(e.pipeline.finalDataAvailable&&e.pipeline.loopReuse.checkpointPeak<=2,"退役epoch未join/checkpoint上限超過");epochs<<"{\"session\":"<<e.pipeline.session<<",\"epoch\":"<<e.renderEpoch<<",\"prepared_only\":"<<(e.preparedOnly?"true":"false")<<",\"checkpoint_peak\":"<<e.pipeline.loopReuse.checkpointPeak<<",\"RAW_frames\":"<<capture.frames(e.pipeline.session)<<"}\n";}
        }
        require(!capture.native.audit.errors&&!capture.native.audit.nonfinite&&!capture.missingOrAffected.load()&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"PCM算術/非有限/callback heap不適合");require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"owner上限超過");
    }
    void close(){hooks.release();engine.reset();audit.save(folder/"final_owned_audit.jsonl");require(audit.complete(),"close配送/即時所有copy/全join/退役未完");
        std::set<std::uint64_t> got;for(const auto& op:audit.operations){require(got.insert(op.id).second&&progressive::terminal(op.state),"終了監査の重複/未終端ID");const auto at=frozen.find(op.id);if(at!=frozen.end())require(at->second==operationJson(op),"終了監査が確定済み39fieldsを変更");}
        require(got==std::set<std::uint64_t>(ids.begin(),ids.end())&&!ph58::RealtimePipeline::executionOwnerCounts().alive,"Accepted集合不一致/close後owner残存");}
    void timing(){std::ofstream out(folder/"normal_timing.json");out<<"{\"clock\":\"steady_clock on normal control thread\",\"unit\":\"milliseconds\",\"Clear_call_to_receipt_ms\":"<<clearReceiptMs<<",\"reenable_call_to_receipt_ms\":"<<newReceiptMs<<",\"reenable_call_to_Clear_owner_retirement_observation_ms\":"<<(oldRetiredMs<0?"null":std::to_string(oldRetiredMs))<<",\"reenable_call_to_new_initial_position_observation_ms\":"<<(newInitialMs<0?"null":std::to_string(newInitialMs))<<",\"Clear_adopted\":"<<(clearAdopted?"true":"false")<<",\"Clear_actual_PCM\":"<<(clearPcm?"true":"false")<<",\"Clear_session\":"<<clearSession<<",\"finite_test_gates_included\":true,\"performance_acceptance_measurement\":false,\"physical_audio_measured\":false}\n";require(bool(out),"通常時刻保存失敗");}
};
// 新Loop準備ではなく、旧ClearのStarted/Done採用保持中に中断する。
// callbackは通常どおり進むため、実際にDoneが先に完了した分岐も保存する。
void runRetainedInterrupt(ReenableFixture& f,const std::string& mode){
    f.initial();f.enterClear("started_done");f.newRange();
    require(f.hooks.stage.entered&&!f.hooks.stage.left,"旧Clear採用workerのgateを保持していない");
    const auto before=f.row(f.clearSpeedID);const auto clearSession=f.capture.firstOther.load();
    require(clearSession&&clearSession!=f.oldSession&&before.clearContinuation&&!progressive::terminal(before.state)&&before.adoptionPending&&before.outputStarted&&before.firstPcmObservedNs&&before.session==clearSession&&f.capture.frames(clearSession)>0,"中断前の保持Clear IDと実RAW/sessionが対応しない");
    require(f.engine->getLoopSnapshot().id==f.newLoopID&&!f.engine->getLoopSnapshot().initialPositionComplete,"旧Clear保持中に新Loopを採用した");
    f.saveRow("retained_Clear_before_action.json",f.clearSpeedID);f.pass("RI04.retained_Clear_actual_PCM_before_action");
    const auto d=f.engine->getPlaybackDiagnostics();
    require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&d.pipeline.loopReuse.checkpointPeak<=2&&d.callbackCppNew&&!*d.callbackCppNew,"保持Clear中断前の供給/保存枠/heap不適合");
    bool cleanupSeen=false;progressive::LoopSpeedOperation final;
    if(mode=="retained_stop"){
        std::atomic<bool> seen{false};std::thread release([&]{const auto end=Tick::now()+std::chrono::seconds(5);while(!f.hooks.followup.cleanupWait.load()&&Tick::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));seen=f.hooks.followup.cleanupWait.load();f.hooks.stage.released=true;});
        try{f.engine->stop();}catch(...){release.join();throw;}release.join();cleanupSeen=seen.load();require(cleanupSeen,"Stopのcleanup待ちより前に旧Clear gateを解放した");
        require(f.engine->getPlaybackState()==State::Stopped&&!f.engine->getLoopSnapshot().enabled&&!f.engine->getLoopSnapshot().clearPending&&!f.engine->getLoopSnapshot().initialPositionComplete,"Stop後に新Loop/Clearを復活または採用した");
        final=f.row(f.clearSpeedID);f.saveRow("retained_Clear_after_Stop_query.json",f.clearSpeedID);f.saveHistory("retained_after_Stop_history.jsonl");
        for(const auto& op:f.engine->loopSpeedHistory())require(progressive::terminal(op.state),"保持Clear中断後に未終端IDが残った");
    }else{
        // Engine APIはこの通常制御threadだけ。別threadは有限gateの解除のみ。
        std::thread release([&]{std::this_thread::sleep_for(std::chrono::milliseconds(10));f.hooks.stage.released=true;});f.engine.reset();release.join();
        f.audit.save(f.folder/"final_owned_audit.jsonl");require(f.audit.complete(),"保持Clearからの直接closeが配送/所有copy/joinを完了しない");
        bool found=false;for(const auto& op:f.audit.operations)if(op.id==f.clearSpeedID){require(!found,"closeのClear ID重複");final=op;found=true;}require(found,"closeに保持Clear IDがない");
    }
    require(!ph58::RealtimePipeline::executionOwnerCounts().alive&&ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"保持Clearの中断後にowner残存/2超過");
    // 旧Clearをまだ保持していたので、後続新LoopのRAWを出してはならない。
    for(const auto& slot:f.capture.counts){const auto session=slot.session.load();if(session&&!f.closedBefore.count(session)&&session!=f.oldSession&&session!=clearSession)require(!slot.frames.load(),"中断した新LoopがRAWを消費した");}
    f.pass("RI05.action_quiesced_joined_no_new_Loop");
    const bool cancelled=final.state==LS::Cancelled,completed=final.state==LS::Completed;
    // 実出力済みClearはReplacedへ戻さない。中断ならCancelledで開始事実を
    // 保持し、quiesceより先に混合が完了していれば実PCM Completedを許す。
    require((cancelled||completed)&&final.outputStarted&&final.firstPcmObservedNs&&final.terminalNs&&final.clearContinuation&&final.session==clearSession&&final.loopID==before.loopID&&final.inputGeneration==before.inputGeneration&&final.sourceSession==before.sourceSession&&final.sourceRenderEpoch==before.sourceRenderEpoch&&final.speedMicros==before.speedMicros,"実出力された保持ClearがReplaced/未出力Cancelled/未終端へ誤分類された");
    require(cancelled?(!final.reason.empty()&&!final.completedNs):final.completedNs>0,"開始済み取消の理由/未完了時刻、または実完了時刻が不正");
    {std::ofstream out(f.folder/"retained_interrupt.json");out<<"{\"mode\":"<<ph58::jsonString(mode)<<",\"same_Clear_ID\":"<<final.id<<",\"clear_session\":"<<clearSession<<",\"actual_RAW_frames\":"<<f.capture.frames(clearSession)<<",\"Stop_cleanup_wait_observed\":"<<(cleanupSeen?"true":"false")<<",\"PartialMixStopDecision_observed\":"<<(f.hooks.partialStopDecision?"true":"false")<<",\"terminal_outcome\":"<<ph58::jsonString(cancelled?"adopted_PCM_invalidated_Cancelled":"Done_finished_actual_PCM_Completed")<<",\"callback_was_gated\":false,\"unoutput_Cancelled_conflated\":false,\"close_only_has_final_Clear_copy\":"<<(mode=="retained_close"?"true":"false")<<",\"before_action\":"<<operationJson(before)<<",\"terminal\":"<<operationJson(final)<<"}\n";require(bool(out),"保持Clear中断の証拠保存失敗");}
    f.pass("RI06.adopted_Clear_terminal_not_Replaced");
    if(f.engine){f.quality();f.pastUnchanged();f.terminalFreeze();}
    require(!f.capture.native.audit.errors&&!f.capture.native.audit.nonfinite&&!f.capture.missingOrAffected.load()&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"保持Clear中断のPCM/heap不適合");
    if(!f.engine){for(const auto& op:f.audit.operations){const auto at=f.frozen.find(op.id);if(at!=f.frozen.end())require(at->second==operationJson(op),"直接closeが既終端39fieldsを書換え");}}
    f.pass("RI07.past_39fields_supply_heap_caps");
    f.close();f.pass("RI08.close_owned_exact_IDs_all_joined");f.timing();
}

void runReenable(ReenableFixture& f,const std::string& mode){
    if(retainedInterrupted(mode)){runRetainedInterrupt(f,mode);return;}
    f.initial();f.enterClear(interrupted(mode)?"preparing":mode);f.newRange();
    const bool paused=mode.rfind("paused_",0)==0;const auto stoppedFrames=f.capture.native.frames.load();
    if(interrupted(mode))f.hooks.followup.arm(ProgressiveControlTestPoint::SeekPreparationStarted);
    f.release(f.hooks.stage);
    if(interrupted(mode)){
        f.until([&]{return f.hooks.followup.entered.load();},"新Loop準備中gate期限");require(f.engine->getLoopSnapshot().id==f.newLoopID&&!f.engine->getLoopSnapshot().initialPositionComplete,"中断前に新Loopが既に採用済み");f.characterizeClear(mode);
        const auto generation=f.context().inputGeneration;
        if(mode=="latest_close"){
            const auto before=f.engine->getPlaybackDiagnostics();require(!before.missingFrames&&!before.underrunCalls&&!before.rejectedWrites&&before.pipeline.loopReuse.checkpointPeak<=2,"直接close前の供給/checkpoint不適合");
            // Engineへの操作はこの通常threadだけ。別threadは有限gateの解除のみ。
            std::thread release([&]{std::this_thread::sleep_for(std::chrono::milliseconds(10));f.hooks.followup.released=true;});f.engine.reset();release.join();
            f.audit.save(f.folder/"final_owned_audit.jsonl");require(f.audit.complete(),"準備中直接close未配送");
            std::set<std::uint64_t> got;for(const auto& op:f.audit.operations){require(progressive::terminal(op.state)&&got.insert(op.id).second,"直接close監査ID不正");if(f.frozen.count(op.id))require(operationJson(op)==f.frozen.at(op.id),"直接closeが39fields変更");}
            f.pass("R05.new_Loop_preparing_then_action");f.pass("R06.no_stale_revival_past_immutable");
            require(!ph58::RealtimePipeline::executionOwnerCounts().alive&&ph58::RealtimePipeline::executionOwnerCounts().peak<=2&&!f.capture.native.audit.errors&&!f.capture.native.audit.nonfinite&&!f.capture.missingOrAffected.load()&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"直接closeのowner/PCM/heap不適合");f.pass("R07.callback_supply_heap_and_owner_caps");
            require(got==std::set<std::uint64_t>(f.ids.begin(),f.ids.end()),"直接close Accepted集合不一致");f.pass("R08.close_owned_copy_exact_IDs_all_joined");f.timing();return;
        }
        std::atomic<bool> released{false};std::thread release([&]{const auto end=Tick::now()+std::chrono::seconds(5);while(!f.hooks.followup.cleanupWait.load()&&Tick::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));released=f.hooks.followup.cleanupWait.load();f.hooks.followup.released=true;});
        try{f.engine->stop();}catch(...){release.join();throw;}release.join();require(released,"Stop解放thread未完了");
        if(mode=="latest_reprepare"){require(f.engine->prepare(f.input,f.options),"同じ入力の新prepare拒否");f.until([&]{return f.engine->getPlaybackState()==State::Ready;},"新入力世代Ready期限");require(f.context().inputGeneration!=generation,"再prepareの入力世代が進まない");}
        f.pass("R05.new_Loop_preparing_then_action");const auto l=f.engine->getLoopSnapshot();require(!l.enabled&&!l.clearPending,"Stop/再prepareで古いLoop/Clear復活");f.pastUnchanged();f.pass("R06.no_stale_revival_past_immutable");f.quality();f.pass("R07.callback_supply_heap_and_owner_caps");f.close();f.pass("R08.close_owned_copy_exact_IDs_all_joined");f.timing();return;
    }
    f.until([&]{const auto l=f.engine->getLoopSnapshot();return l.id==f.newLoopID&&l.initialPositionComplete&&!f.engine->getPlaybackDiagnostics().retiringPipeline;},"新ReturnToA初期位置/退役期限");f.newInitialMs=msSince(f.requestAt);f.characterizeClear(mode);
    if(paused){require(f.engine->getPlaybackState()==State::Paused&&!f.engine->getStateSnapshot().resumePending&&f.capture.native.frames.load()==stoppedFrames&&f.engine->getCurrentPlaybackPosition().inputFrame==f.rate/4&&f.engine->getLoopSnapshot().cycles==0,"Paused再ONの初期A静止/無消費契約違反");
        std::this_thread::sleep_for(std::chrono::milliseconds(100));f.healthy();require(f.capture.native.frames.load()==stoppedFrames&&f.engine->getCurrentPlaybackPosition().inputFrame==f.rate/4,"明示Resume前にA/PCM進行");require(f.engine->resume(),"新Loopの明示Resume拒否");}
    else require(f.engine->getPlaybackState()==State::Playing,"Playing意思が失われた");f.pass("R05.new_ReturnToA_and_explicit_play_intent");
    f.pastUnchanged();f.saveHistory("new_Loop_history.jsonl");f.pass("R06.past_and_terminal_39fields_immutable");
    f.until([&]{return f.engine->getLoopSnapshot().cycles>=1;},"新Loopの自然B未観測");const auto l=f.engine->getLoopSnapshot();require(l.id==f.newLoopID&&l.enabled&&!l.clearPending&&l.lastBoundary&&l.lastBoundary->loopID==f.newLoopID&&l.lastBoundary->inputA==f.rate/4&&l.lastBoundary->inputBExclusive==f.rate/4+f.rate/2,"旧Clear復活/新Loop実境界identity不一致");f.pass("R07.A_then_natural_B_without_stale_Clear");
    const auto history=f.engine->loopSpeedHistory();std::set<std::uint64_t> got;for(const auto& op:history)require(got.insert(op.id).second&&progressive::terminal(op.state),"Accepted ID重複/未終端");require(got==std::set<std::uint64_t>(f.ids.begin(),f.ids.end())&&f.ids.size()==2,"Accepted全ID集合不一致");f.pass("R08.exact_Accepted_IDs_terminal");
    f.quality();f.pastUnchanged();f.pass("R09.callback_supply_heap_and_owner_caps");f.close();f.pass("R10.close_owned_copy_exact_IDs_all_joined");f.timing();
}
}
int main(int argc,char** argv){
    if(argc!=6){std::cerr<<"MODE INPUT baseline|candidate NEW_OUTPUT_DIR SOURCE_LIST_SHA256\n";return 2;}
    int code=1;std::thread owner([&]{std::unique_ptr<ReenableFixture> f;std::filesystem::path folder;bool owned=false;std::vector<std::string> expected;const std::string mode=argv[1],preset=argv[3];
        try{expected=reenableChecks(mode);const std::string source=argv[5];require(preset=="baseline"||preset=="candidate","preset不正");require(source.size()==64&&source.find_first_not_of("0123456789abcdef")==std::string::npos,"source SHA不正");
            folder=std::filesystem::absolute(argv[4]);require(std::filesystem::create_directories(folder),"既存証拠を上書きしない");owned=true;
            std::ofstream manifest(folder/"EXPECTED.json");manifest<<"{\"schema\":1,\"suite\":\"phase62_Clear_reenable\",\"mode\":"<<ph58::jsonString(mode)<<",\"preset\":"<<ph58::jsonString(preset)<<",\"expected\":"<<expected.size()<<",\"expected_Accepted_external_IDs\":2,\"source_list_sha256\":"<<ph58::jsonString(source)<<",\"input_sha256\":"<<ph58::jsonString(fileHash(argv[2]))<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))<<",\"driver_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::path(__FILE__)))<<",\"expected_IDs\":[";for(std::size_t i=0;i<expected.size();++i)manifest<<(i?",":"")<<ph58::jsonString(expected[i]);manifest<<"],\"callback_gate\":false,\"normal_worker_finite_gates_only\":true,\"all_operation_fields_compared\":39,\"independent_DSP\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"reprepare_scope\":\"same_path_new_input_generation\"}\n";manifest.close();require(bool(manifest),"EXPECTED保存失敗");
            phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"heap検出器自己試験失敗");phase61_heap_reset();hostCallbackCppNew=0;
            f=std::make_unique<ReenableFixture>(argv[2],preset=="baseline"?Preset::Baseline:Preset::Candidate,folder,expected);runReenable(*f,mode);require(f->passed==expected,"全check集合/件数不一致");
            std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"suite\":\"phase62_Clear_reenable\",\"mode\":"<<ph58::jsonString(mode)<<",\"status\":\"PASS\",\"run_complete\":true,\"expected\":"<<expected.size()<<",\"executed\":"<<f->passed.size()<<",\"Accepted_IDs\":[";for(std::size_t i=0;i<f->ids.size();++i)summary<<(i?",":"")<<f->ids[i];summary<<"],\"callback_gate\":false,\"independent_DSP\":\"NOT_RUN\",\"public_go\":false}\n";summary.close();require(bool(summary),"SUMMARY保存失敗");std::ifstream saved(folder/"SUMMARY.json");std::cout<<saved.rdbuf();code=0;
        }catch(const std::exception& error){std::cerr<<error.what()<<'\n';if(f){f->hooks.release();try{if(f->engine){f->saveHistory("failure_history.jsonl");f->engine.reset();}f->audit.save(folder/"failure_owned_audit.jsonl");}catch(...){}}
            if(owned){std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"suite\":\"phase62_Clear_reenable\",\"mode\":"<<ph58::jsonString(mode)<<",\"status\":\"FAIL\",\"run_complete\":false,\"expected\":"<<expected.size()<<",\"executed\":"<<(f?f->passed.size():0)<<",\"reason\":"<<ph58::jsonString(error.what())<<"}\n";}}
    });owner.join();return code;
}
