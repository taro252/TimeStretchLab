// Phase 62の採用競合・初回供給保持・実内部4096件を公開APIで検査する。
// 各modeは別processで直列実行する。callbackへ待機・I/Oを追加しない。
#define PHASE62_PLAYING_LEDGER_NO_MAIN 1
#include "Phase62PlayingLedgerNative.cpp"
#include <exception>

namespace {
namespace rev59=ts::prototype::phase59;
using InternalResult=ts::prototype::Phase39RequestResult;

struct ReviewCapture {
    NativeCapture native;
    std::atomic<std::uint64_t> normalSession{0},firstNewSession{0},newSourceFrames{0};
    std::array<std::atomic<std::uint64_t>,64> seenSessions{};
    explicit ReviewCapture(std::size_t channels):native(channels){}
    static void raw(void* pointer,const float*const* pcm,std::size_t count,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& c=*static_cast<ReviewCapture*>(pointer);NativeCapture::raw(&c.native,pcm,count,at,generation,epoch,session);
        c.seenSessions[session%c.seenSessions.size()].store(session,std::memory_order_release);
        if(count&&session!=c.normalSession.load(std::memory_order_relaxed)){
            c.newSourceFrames.fetch_add(count,std::memory_order_release);
            std::uint64_t empty=0;c.firstNewSession.compare_exchange_strong(empty,session,std::memory_order_release);
        }
    }
    static void output(void* pointer,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        NativeCapture::output(&static_cast<ReviewCapture*>(pointer)->native,pcm,span);
    }
    bool sawSession(std::uint64_t session)const noexcept{return session&&seenSessions[session%seenSessions.size()].load(std::memory_order_acquire)==session;}
};
enum class DecisionMode {None,CancelWins,StartedWins};
struct ReviewHooks {
    WorkerGate dispatch,selected,prepared,published;
    ReviewCapture* capture=nullptr;
    std::atomic<ProgressiveControlTestPoint> decisionPoint{ProgressiveControlTestPoint::SpeedReplacementDecision};
    std::atomic<DecisionMode> decisionMode{DecisionMode::None};
    std::atomic<bool> decisionArmed{false},decisionEntered{false},decisionExpired{false},decisionHadPcmBefore{false};
    std::atomic<std::uint64_t> decisionPcmSession{0},decisionPcmFrames{0};
    void releaseAll()noexcept{dispatch.released=true;selected.released=true;prepared.released=true;published.released=true;}
    static void event(void* pointer,ProgressiveControlTestPoint point)noexcept{
        auto& h=*static_cast<ReviewHooks*>(pointer);
        WorkerGate::event(&h.dispatch,point);WorkerGate::event(&h.selected,point);WorkerGate::event(&h.prepared,point);WorkerGate::event(&h.published,point);
        if(point!=h.decisionPoint.load()||!h.decisionArmed.exchange(false))return;
        h.decisionHadPcmBefore=h.capture->firstNewSession.load(std::memory_order_acquire)!=0;
        h.decisionEntered.store(true,std::memory_order_release);
        if(h.decisionMode.load()==DecisionMode::StartedWins){
            // このhookはengine mutex内。Engine APIは呼ばず、実callbackの値だけを見る。
            const auto end=Tick::now()+std::chrono::seconds(2);
            while(!h.capture->firstNewSession.load(std::memory_order_acquire)&&Tick::now()<end)
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            if(!h.capture->firstNewSession.load(std::memory_order_acquire))h.decisionExpired=true;
        }
        h.decisionPcmSession=h.capture->firstNewSession.load(std::memory_order_acquire);
        h.decisionPcmFrames=h.capture->newSourceFrames.load(std::memory_order_acquire);
    }
};
struct CheckpointProbe {
    std::atomic<bool> armed{false},failNewWorkgroup{false};
    std::atomic<std::uint64_t> targetSession{0},failedSession{0},failedOperation{0},failHits{0},permitCalls{0};
    std::atomic<std::uint64_t> workgroupFailureSession{0},workgroupFailureHits{0};
    static void event(void* pointer,ph58::ControlTestPoint point,std::uint64_t,std::uint64_t)noexcept{
        if(point==ph58::ControlTestPoint::CheckpointPermit)static_cast<CheckpointProbe*>(pointer)->permitCalls.fetch_add(1,std::memory_order_relaxed);
    }
    static bool fail(void* pointer,ph58::ControlTestPoint point,std::uint64_t session,std::uint64_t operation)noexcept{
        auto& p=*static_cast<CheckpointProbe*>(pointer);
        if(point==ph58::ControlTestPoint::WorkgroupJoin&&session!=p.targetSession.load(std::memory_order_acquire)&&p.failNewWorkgroup.exchange(false)){
            p.workgroupFailureSession=session;p.workgroupFailureHits.fetch_add(1,std::memory_order_release);return true;
        }
        if(point!=ph58::ControlTestPoint::CheckpointPermit||session!=p.targetSession.load(std::memory_order_acquire)||!p.armed.exchange(false))return false;
        p.failedSession=session;p.failedOperation=operation;p.failHits.fetch_add(1,std::memory_order_release);return true;
    }
};

std::vector<std::string> reviewChecks(const std::string& mode){
    if(mode=="a1_cancel")return {"A1.normal_Playing_and_old_ID_bound","A1.Requested_decision_window_observed","A1.cancel_wins_old_Replaced_no_old_PCM","A1.latest_Completed_actual_PCM","A1.exact_IDs_and_terminal_types","normal_supply_heap_owner_audit"};
    if(mode=="a1_started")return {"A1.normal_Playing_and_old_ID_bound","A1.Requested_decision_window_observed","A1.Started_wins_old_Completed_actual_PCM","A1.latest_Completed_actual_PCM","A1.exact_IDs_and_terminal_types","normal_supply_heap_owner_audit"};
    if(mode=="a2_initial_supply")return {"A2.normal_dspDone_unconsumed_Playing","A2.Keep_no_self_repeat_old_ID_bound","A2.latest_retains_required_old_without_false_facts","A2.actual_B_old_Completed_and_latest_Completed","A2.exact_IDs_and_terminal_types","normal_supply_heap_owner_audit"};
    if(mode=="a2_checkpoint_supply")return {"D09.normal_Playing_before_dspDone","D09.real_CheckpointPermit_failure_and_initial_ID_bound","D09.required_old_supply_retained_without_false_facts","D09.actual_B_old_Completed_and_latest_Completed","D09.checkpoint_budget_and_later_preparation_recovery","D09.exact_IDs_and_terminal_types","normal_supply_heap_owner_audit"};
    if(mode=="a2_clear_started")return {"A2_CLEAR.real_CheckpointPermit_failure_initial75_bound","A2_CLEAR.latest200_waits_required75_without_false_facts","A2_CLEAR.Requested_Clear_cancellation_window","A2_CLEAR.Started_wins_old75_Completed_actual_PCM","A2_CLEAR.latest200_Clear_EOF_Cancelled_without_PCM","A2_CLEAR.exact_IDs_terminal_types_and_past_immutable","normal_supply_heap_owner_audit"};
    if(mode=="b_internal4096")return {"B.normal_Playing_same_owner_4096_Duplicate","B.all_internal_records_exact_and_no_Accepted_history","B.Keep_same_owner_self_repeat_Ready","B.external_Accepted_then_real_InternalLimit_Failed","B.old_PCM_history_and_preparation_retirement","B.exact_external_ID_and_final_cause","normal_supply_heap_owner_audit"};
    if(mode=="f01_dsp_done"||mode=="f01_checkpoint")return {"F01.normal_no_self_repeat_condition","F01.selected_job_then_latest_B_window","F01.actual_initial_B_session_epoch_PCM","F01.latest_B_Completed_and_A_past_immutable","F01.required_A_protected_and_Completed","F01.exact_IDs_and_terminal_types","normal_supply_heap_owner_audit"};
    if(mode=="f01_selected_stop"||mode=="f01_selected_clear"||mode=="f01_selected_failure")return {"F01_CANCEL.normal_no_self_repeat_and_selected_A","F01_CANCEL.latest_B_accepted_no_false_facts","F01_CANCEL.action_effective_no_A_or_B_PCM","F01_CANCEL.prepared_owner_joined_and_followup_recovers","F01_CANCEL.direct_close_exact_IDs_reasoned_terminal","normal_supply_heap_owner_audit"};
    throw std::runtime_error("未知のreview modeです");
}

struct ReviewFixture {
    const std::filesystem::path folder;
    ReviewCapture capture;
    ReviewHooks hooks;
    CheckpointProbe checkpoint;
    ProgressiveOptions options;
    FinalLedgerSink finalAudit;
    std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
    std::vector<std::string> expected,passed;
    std::vector<std::uint64_t> ids;
    std::ofstream checks,receipts;
    progressive::LoopContext normalContext;
    std::uint64_t inputFrames=0,loopID=0;
    unsigned rate=0;
    ReviewFixture(const std::filesystem::path& input,Preset preset,const std::filesystem::path& out,std::vector<std::string> wanted):folder(out),capture(ts::WavStreamReader(input).channels()),expected(std::move(wanted)),checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl"){
        ts::WavStreamReader wav(input);inputFrames=wav.frames();rate=wav.sampleRate();hooks.capture=&capture;
        options.preset=preset;options.initialSpeed=1.;options.allowExperimentalLoops=true;options.callbackRecordLimit=8192;
        options.controlTestHooks={&hooks,ReviewHooks::event};options.observerContext=&capture;options.observeEpochPcm=ReviewCapture::raw;options.observeOutputPcm=ReviewCapture::output;
        options.pipelineControlTestHooks={&checkpoint,CheckpointProbe::event,CheckpointProbe::fail};
        options.finalLoopSpeedAuditContext=&finalAudit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew,std::memory_order_relaxed);callbackCounting=false;},[]()noexcept{return callbackNew;}};
        require(engine->prepare(input,options),"通常prepare拒否");until([&]{return engine->getPlaybackState()==State::Ready;},"通常Ready期限");
        normalContext=context();capture.normalSession=normalContext.session;
    }
    ~ReviewFixture(){hooks.releaseAll();if(engine)engine->stop();}
    void healthy(){
        require(!hooks.dispatch.expired&&!hooks.selected.expired&&!hooks.prepared.expired&&!hooks.published.expired&&!hooks.decisionExpired,"有限hookの期限超過");
        require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"実行ownerが2を超過");
        if(engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);
    }
    template<class P> void until(P predicate,const char* why,unsigned seconds=60){
        const auto end=Tick::now()+std::chrono::seconds(seconds);
        while(!predicate()){healthy();require(Tick::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();
    }
    // mutex内のdecision hook実行中は通常のuntil/Engine APIを使用しない。
    template<class P> void atomicUntil(P predicate,const char* why,unsigned seconds=5){
        const auto end=Tick::now()+std::chrono::seconds(seconds);
        while(!predicate()){require(!hooks.decisionExpired&&!hooks.published.expired,"競合窓hook期限超過");require(Tick::now()<end,why);std::this_thread::sleep_for(std::chrono::microseconds(100));}
    }
    progressive::LoopContext context(){const auto s=engine->getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
    void playNormal(){require(!engine->getLoopSnapshot().enabled&&engine->play(),"通常Playing開始拒否");until([&]{return capture.native.frames.load()>=512;},"通常PCM未観測");require(context().session==normalContext.session,"通常ownerが変化");}
    void pass(const char* id){require(passed.size()<expected.size()&&expected[passed.size()]==id,"check ID集合/順序不一致");passed.emplace_back(id);checks<<"{\"id\":"<<ph58::jsonString(id)<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"check保存失敗");}
    progressive::LoopSpeedOperation row(std::uint64_t id){const auto op=engine->loopSpeedOperation(id);require(op.has_value(),"受付IDが台帳にない");return *op;}
    void record(const char* call,double speed,const progressive::LoopSpeedReceipt& r,progressive::LoopContext c){
        receipts<<"{\"call\":"<<ph58::jsonString(call)<<",\"speed\":"<<speed<<",\"id\":"<<r.id<<",\"accepted\":"<<(r.accepted?"true":"false")<<",\"duplicate\":"<<(r.duplicate?"true":"false")<<",\"code\":"<<int(r.code)<<",\"generation\":"<<c.inputGeneration<<",\"session\":"<<c.session<<",\"epoch\":"<<c.renderEpoch<<",\"reason\":"<<ph58::jsonString(r.reason)<<"}\n";receipts.flush();require(bool(receipts),"receipt保存失敗");
        if(r.accepted&&!r.duplicate){require(r.id&&r.code==Code::Accepted,"新規受付ID不正");require(std::find(ids.begin(),ids.end(),r.id)==ids.end(),"新規受付ID重複");ids.push_back(r.id);}
    }
    progressive::LoopSpeedReceipt request(const char* call,double speed){const auto c=context();const auto r=engine->requestLoopSpeed(speed,c);record(call,speed,r,c);require(r.accepted&&!r.duplicate&&r.id,"新規Loop要求が拒否された");return r;}
    void saveLedger(const char* name){std::ofstream out(folder/name);for(const auto& op:engine->loopSpeedHistory())out<<operationJson(op)<<'\n';require(bool(out),"台帳保存失敗");}
    void exactIds(const std::vector<LS>& states){
        require(states.size()==ids.size(),"期待終端数不一致");const auto history=engine->loopSpeedHistory();std::set<std::uint64_t> actual,wanted(ids.begin(),ids.end());
        for(const auto& op:history){require(actual.insert(op.id).second,"台帳ID重複");require(progressive::terminal(op.state),"外部ID未終端");}
        require(wanted==actual,"受付ID集合と台帳ID集合が不一致");for(std::size_t i=0;i<ids.size();++i)require(row(ids[i]).state==states[i],"終端種別不一致");
    }
    progressive::LoopSpeedOperation completed(std::uint64_t id){until([&]{return progressive::terminal(row(id).state);},"速度要求終端期限");auto op=row(id);require(op.state==LS::Completed,"採用した要求がCompletedでない");return op;}
    void actualPcm(const progressive::LoopSpeedOperation& op){require(op.outputStarted&&op.firstPcmObservedNs&&op.session&&op.renderEpoch&&!op.noChange&&capture.sawSession(op.session),"Completedと実session/epoch/PCMが対応しない");}
    void release(WorkerGate& gate){gate.released=true;until([&]{return gate.left.load();},"通常側gate解放期限");}
    progressive::LoopSpeedReceipt bindInitial(progressive::LoopStartPolicy policy,std::uint64_t b,bool beforePublication=false,bool checkpointFailure=false){
        hooks.dispatch.arm(ProgressiveControlTestPoint::LoopJobDispatch);hooks.published.arm(ProgressiveControlTestPoint::SwitchPublished);
        if(beforePublication)hooks.prepared.arm(ProgressiveControlTestPoint::SeekPreparationStarted);
        progressive::LoopOptions start;start.startPolicy=policy;const auto result=engine->requestLoopRange(0,b,context(),start);require(result.accepted,"PlayingからLoop受付拒否");loopID=result.id;
        until([&]{return hooks.dispatch.entered.load();},"job選択前dispatch hook未到達");
        if(checkpointFailure)until([&]{return checkpoint.failHits.load()==1&&engine->getPlaybackDiagnostics().pipeline.loopReuse.normalPreparation==ph58::NormalLoopReuseState::LimitReached;},"実保存点permit失敗callerのLimitReached未到達");
        const auto old=request("old_75_bound_before_job_selection",.75);require(row(old.id).state==LS::Pending,"job選択前の旧IDがPendingでない");
        release(hooks.dispatch);
        if(beforePublication)until([&]{return hooks.prepared.entered.load();},"初回準備開始hook未到達");
        else until([&]{return hooks.published.entered.load();},"初回handoff公開hook未到達");
        const auto bound=row(old.id);require(bound.state==LS::Preparing&&bound.preparingNs&&(beforePublication||bound.readyNs)&&bound.preparationVersion&&bound.speedMicros==750000&&bound.sourceSession==normalContext.session&&bound.inputGeneration==normalContext.inputGeneration&&!bound.outputStarted&&!bound.committed,"旧外部IDと初回準備jobの結び付き不正");
        require(engine->getLoopSnapshot().speedRequestID==old.id&&engine->getLoopSnapshot().preparationCount==1,"初回jobが別要求/複数jobへ分岐した");saveLedger("bound_preparation_ledger.jsonl");return old;
    }
    void qualityAndOwnership(){
        if(engine->getPlaybackState()==State::Playing)require(engine->pause(),"監査前Pause拒否");
        const auto d=engine->getPlaybackDiagnostics();const auto loop=engine->getLoopSnapshot();const auto n=engine->getNativeDiagnostics();
        require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!loop.failurePaddingFrames&&!loop.outputAffectedFrames&&!loop.safetyStopFrames,"通常供給に不足/加工失敗/安全停止");
        require(d.callbackCppNew&&!*d.callbackCppNew&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback heapの検出器不在または確保/解放あり");
        require(!capture.native.audit.errors&&!capture.native.audit.nonfinite,"RAW順序/境界補正/NaN監査失敗");require(engine->seekHistory().empty(),"内部操作が外部seek履歴へ混入");
        writePhase62Trace(folder/"callbacks_all_spans.jsonl",engine->loopCallbackRecords());writePhase62Trace(folder/"clock_anomaly_window.jsonl",engine->loopClockAnomalyRecords());
        std::ofstream observed(folder/"native_observation.json");observed<<"{\"source_rate\":"<<rate<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"output_frames\":"<<capture.native.frames.load()<<",\"missing\":"<<d.missingFrames<<",\"callback_deadlines_observed\":"<<n.deadlineMisses<<",\"worker_deadlines_observed\":"<<d.workerDeadlineMisses<<",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"callback_gate\":false}\n";
        engine->stop();std::ofstream epochs(folder/"closed_epochs.jsonl");for(const auto& epoch:engine->closedEpochs()){
            require(epoch.pipeline.finalDataAvailable,"旧/準備epochのjoin未完了");const auto& w=epoch.pipeline.scheduling;
            if(checkpoint.workgroupFailureHits.load()==1&&epoch.pipeline.session==checkpoint.workgroupFailureSession.load())require(!w.active&&w.joinErrors==1&&w.joins==w.leaves&&w.promotions==w.restores,"注入したWorkgroup join失敗版の復元未完了");
            else require(!w.active&&w.joins==w.leaves&&w.leaves==w.restores,"退役時Workgroup未解放");
            epochs<<"{\"session\":"<<epoch.pipeline.session<<",\"input_generation\":"<<epoch.pipeline.inputGeneration<<",\"render_epoch\":"<<epoch.renderEpoch<<",\"prepared_only\":"<<(epoch.preparedOnly?"true":"false")<<",\"final_data_available\":true,\"PCM_observed\":"<<(capture.sawSession(epoch.pipeline.session)?"true":"false")<<",\"operation_records_retained\":"<<epoch.operations.size()<<",\"operation_records_dropped\":"<<epoch.droppedOperations<<",\"workgroup_joins\":"<<w.joins<<",\"workgroup_leaves\":"<<w.leaves<<",\"workgroup_restores\":"<<w.restores<<"}\n";
        }require(bool(epochs),"退役監査保存失敗");
        const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"停止後owner残存/peak超過");
    }
};

void adoptionRace(ReviewFixture& f,bool started){
    require(f.inputFrames>=std::uint64_t(f.rate)*9,"A1は9秒以上の入力が必要");f.playNormal();const auto old=f.bindInitial(progressive::LoopStartPolicy::ReturnToA,std::uint64_t(f.rate)*8,true);
    f.pass("A1.normal_Playing_and_old_ID_bound");require(!f.capture.firstNewSession.load(),"最新要求前に旧版が採用済み: Requested窓を取り逃した");
    f.hooks.decisionMode=started?DecisionMode::StartedWins:DecisionMode::CancelWins;f.hooks.decisionArmed=true;
    progressive::LoopSpeedReceipt latest;std::exception_ptr thrown;std::atomic<bool> returned{false};const auto c=f.normalContext;
    {
        // 通常API呼出しだけを別threadへ移す。callbackは通常どおり進む。
        std::jthread requester([&]{try{
            const auto end=Tick::now()+std::chrono::seconds(20);
            while(!f.hooks.published.entered.load(std::memory_order_acquire)&&Tick::now()<end)std::this_thread::sleep_for(std::chrono::microseconds(50));
            require(f.hooks.published.entered.load(),"別threadがhandoff公開を観測できない");latest=f.engine->requestLoopSpeed(2.,c);
        }catch(...){thrown=std::current_exception();}returned.store(true,std::memory_order_release);});
        // 公開前に要求threadを待機させ、公開直後にAPIへ進ませる。
        f.hooks.prepared.released=true;
        f.atomicUntil([&]{return returned.load(std::memory_order_acquire);},"最新速度API/decision hookの終了期限");
    }
    if(thrown)std::rethrow_exception(thrown);f.record("latest_200_at_replacement_decision",2.,latest,c);
    {
        std::ofstream window(f.folder/"decision_window.json");window<<"{\"old_external_ID\":"<<old.id<<",\"normal_session\":"<<f.normalContext.session<<",\"decision_entered\":"<<(f.hooks.decisionEntered?"true":"false")<<",\"new_PCM_before_decision\":"<<(f.hooks.decisionHadPcmBefore?"true":"false")<<",\"new_PCM_session_during_decision\":"<<f.hooks.decisionPcmSession.load()<<",\"new_PCM_frames_during_decision\":"<<f.hooks.decisionPcmFrames.load()<<",\"decision_expired\":"<<(f.hooks.decisionExpired?"true":"false")<<",\"callback_gate\":false,\"old_row_after_decision\":"<<operationJson(f.row(old.id))<<"}\n";require(bool(window),"競合窓観測の保存失敗");
    }
    require(latest.accepted&&!latest.duplicate&&latest.id,"競合中の最新要求が受付されなかった");require(f.hooks.published.entered&&f.hooks.decisionEntered&&!f.hooks.decisionHadPcmBefore,"Requested取消判定前の実窓を観測できなかった");
    f.pass("A1.Requested_decision_window_observed");
    if(started){require(f.hooks.decisionPcmSession&&f.hooks.decisionPcmFrames,"判定hook中の実callback採用/PCMなし");require(f.row(old.id).state!=LS::Replaced,"Started勝利した旧IDを早期Replacedにした");}
    else{require(!f.hooks.decisionPcmSession&&!f.hooks.decisionPcmFrames,"取消勝利前に旧版PCMを既に採用");const auto cancelled=f.row(old.id);require(cancelled.state==LS::Replaced&&!cancelled.outputStarted&&!cancelled.committed,"取消勝利した旧IDの終端/事実が不正");}
    f.release(f.hooks.published);
    if(started){const auto adopted=f.completed(old.id);f.actualPcm(adopted);require(adopted.session==f.hooks.decisionPcmSession.load(),"旧IDとhook中採用sessionの対応不一致");f.pass("A1.Started_wins_old_Completed_actual_PCM");}
    else{
        f.until([&]{for(const auto& epoch:f.engine->closedEpochs())if(epoch.preparedOnly&&epoch.pipeline.finalDataAvailable)return true;return false;},"取消準備版の退役未完了");
        std::size_t retired=0;for(const auto& epoch:f.engine->closedEpochs())if(epoch.preparedOnly){++retired;require(!f.capture.sawSession(epoch.pipeline.session),"取消した旧準備版PCMが新たに出力された");}require(retired==1,"取消対象の準備版を一意に確定できない");f.pass("A1.cancel_wins_old_Replaced_no_old_PCM");
    }
    const auto savedPast=operationJson(f.row(old.id));const auto applied=f.completed(latest.id);f.actualPcm(applied);f.until([&]{return f.engine->getStateSnapshot().appliedTargetSpeed==2.;},"最新200の実適用期限");require(operationJson(f.row(old.id))==savedPast,"新要求の適用が旧確定履歴を変更した");f.pass("A1.latest_Completed_actual_PCM");
    f.exactIds({started?LS::Completed:LS::Replaced,LS::Completed});f.saveLedger("terminal_ledger.jsonl");f.pass("A1.exact_IDs_and_terminal_types");f.qualityAndOwnership();f.pass("normal_supply_heap_owner_audit");
}

void initialSupply(ReviewFixture& f,bool checkpointFailure=false){
    if(checkpointFailure){
        require(f.inputFrames>=f.rate/2&&f.inputFrames<=std::uint64_t(f.rate)*2,"D09は500ms〜2秒の全曲入力を使う（推奨1秒）");
        f.playNormal();require(!f.engine->getPlaybackDiagnostics().pipeline.dspDone,"保存点失敗前にproducerが既に終了");
        f.checkpoint.targetSession=f.normalContext.session;f.checkpoint.armed=true;f.pass("D09.normal_Playing_before_dspDone");
    }else{
        require(f.inputFrames>=f.rate/10&&f.inputFrames<=12288,"A2は100ms以上かつ両PresetのFIFO先行量以下の短い全曲入力が必要");
        f.until([&]{return f.engine->getPlaybackDiagnostics().pipeline.dspDone;},"短曲の実dspDone期限");const auto ready=f.engine->getPlaybackDiagnostics();require(!ready.pipeline.consumed&&ready.pipeline.published==f.inputFrames,"短曲は未消費FIFOを全量保持する必要がある");
        f.playNormal();const auto playing=f.engine->getPlaybackDiagnostics();require(playing.pipeline.dspDone&&playing.pipeline.consumed<playing.pipeline.published&&f.engine->getPlaybackState()==State::Playing,"dspDone+未消費FIFOの通常Playing条件不成立");f.pass("A2.normal_dspDone_unconsumed_Playing");
    }
    const auto old=f.bindInitial(progressive::LoopStartPolicy::KeepPosition,f.inputFrames,false,checkpointFailure);const auto loop=f.engine->getLoopSnapshot();
    {
        const auto supplied=f.engine->getPlaybackDiagnostics();std::ofstream conditions(f.folder/"initial_supply_conditions.json");conditions<<"{\"input_frames\":"<<f.inputFrames<<",\"rate\":"<<f.rate<<",\"normal_session\":"<<f.normalContext.session<<",\"current_session\":"<<supplied.session<<",\"dsp_done\":"<<(supplied.pipeline.dspDone?"true":"false")<<",\"published\":"<<supplied.pipeline.published<<",\"consumed\":"<<supplied.pipeline.consumed<<",\"self_repeat\":"<<(loop.reusable?"true":"false")<<",\"old_external_ID\":"<<old.id<<",\"old_preparation\":"<<operationJson(f.row(old.id))<<"}\n";require(bool(conditions),"初回供給条件の保存失敗");
    }
    require(!loop.reusable&&!f.capture.firstNewSession.load(),"自己反復無効/初回供給採用前の条件不成立");
    if(checkpointFailure){require(f.checkpoint.failHits.load()==1&&f.checkpoint.failedSession.load()==f.normalContext.session&&!f.checkpoint.armed&&f.engine->getPlaybackDiagnostics().pipeline.loopReuse.normalPreparation==ph58::NormalLoopReuseState::LimitReached,"実permit失敗のsession/caller状態不一致");f.pass("D09.real_CheckpointPermit_failure_and_initial_ID_bound");}
    else{require(f.engine->getPlaybackDiagnostics().pipeline.dspDone,"短曲producerのdspDone事実が消えた");f.pass("A2.Keep_no_self_repeat_old_ID_bound");}
    const auto latest=f.request("latest_200_while_initial_supply_required",2.);const auto retained=f.row(old.id);
    require(!progressive::terminal(retained.state)&&!retained.committed&&!retained.outputStarted&&!retained.firstPcmObservedNs,"未採用の初回必須供給を終端化/採用事実を捏造した");f.pass(checkpointFailure?"D09.required_old_supply_retained_without_false_facts":"A2.latest_retains_required_old_without_false_facts");f.release(f.hooks.published);
    const auto adopted=f.completed(old.id);f.actualPcm(adopted);require(adopted.session==f.capture.firstNewSession.load(),"初回B採用と旧外部IDのsession不一致");
    f.until([&]{const auto events=f.engine->loopHistory();return !events.empty()&&events.front().oldOutputEnd==f.inputFrames&&events.front().callbackFrame==f.inputFrames&&events.front().inputA==0&&events.front().inputBExclusive==f.inputFrames&&!events.front().overlapFrames&&events.front().newEpoch==adopted.renderEpoch;},"実初回Bの境界/採用epoch未観測");
    const auto savedPast=operationJson(adopted);const auto applied=f.completed(latest.id);f.actualPcm(applied);require(f.engine->getStateSnapshot().appliedTargetSpeed==2.,"最新速度を失った");require(operationJson(f.row(old.id))==savedPast,"最新速度が初回採用済み履歴を変更した");f.pass(checkpointFailure?"D09.actual_B_old_Completed_and_latest_Completed":"A2.actual_B_old_Completed_and_latest_Completed");
    if(checkpointFailure){
        const auto resource=f.engine->getPlaybackDiagnostics().pipeline.loopReuse;require(f.checkpoint.failHits.load()==1&&f.checkpoint.permitCalls.load()>=3&&resource.checkpointPeak<=2&&resource.checkpointStates<=2,"保存点失敗後の枠/後続準備復旧が不正");
        std::ofstream permits(f.folder/"checkpoint_permit_observation.json");permits<<"{\"failed_session\":"<<f.checkpoint.failedSession.load()<<",\"failed_operation\":"<<f.checkpoint.failedOperation.load()<<",\"fail_hits\":"<<f.checkpoint.failHits.load()<<",\"permit_calls\":"<<f.checkpoint.permitCalls.load()<<",\"checkpoint_peak\":"<<resource.checkpointPeak<<",\"checkpoint_states\":"<<resource.checkpointStates<<",\"old_external_ID\":"<<old.id<<",\"latest_external_ID\":"<<latest.id<<",\"later_preparation_completed\":true}\n";require(bool(permits),"保存点permit観測保存失敗");f.pass("D09.checkpoint_budget_and_later_preparation_recovery");
    }
    f.exactIds({LS::Completed,LS::Completed});f.saveLedger("terminal_ledger.jsonl");f.pass(checkpointFailure?"D09.exact_IDs_and_terminal_types":"A2.exact_IDs_and_terminal_types");f.qualityAndOwnership();f.pass("normal_supply_heap_owner_audit");
}

struct SelectedSupply {
    progressive::LoopSpeedReceipt old,latest;
    progressive::LoopSpeedOperation beforeLatest,afterLatest,latestAfterAccept;
    std::uint64_t selectedNs=0,selectedVersion=0,selectedCount=0,published=0,consumed=0;
};
void normalWithoutSelfRepeat(ReviewFixture& f,bool checkpointFailure){
    if(checkpointFailure){
        require(f.inputFrames==f.rate,"F01 checkpoint条件は正確に1秒の全曲入力を使う");
        f.playNormal();require(!f.engine->getPlaybackDiagnostics().pipeline.dspDone,"F01 checkpoint拒否前に通常producerが終了済み");
        f.checkpoint.targetSession=f.normalContext.session;f.checkpoint.armed=true;
    }else{
        require(f.inputFrames>=f.rate/10&&f.inputFrames<=12288,"F01 dspDone条件は100ms以上・12288フレーム以下の短い全曲入力を使う");
        f.until([&]{return f.engine->getPlaybackDiagnostics().pipeline.dspDone;},"F01短曲producerのdspDone期限");
        const auto d=f.engine->getPlaybackDiagnostics();require(!d.pipeline.consumed&&d.pipeline.published==f.inputFrames,"F01短曲の未消費FIFO全量保持なし");
        f.playNormal();const auto playing=f.engine->getPlaybackDiagnostics();require(playing.pipeline.dspDone&&playing.pipeline.consumed<playing.pipeline.published,"F01通常Playing+dspDone+未消費PCMの条件不成立");
    }
}
SelectedSupply selectInitialSupply(ReviewFixture& f,bool checkpointFailure){
    SelectedSupply s;f.hooks.dispatch.arm(ProgressiveControlTestPoint::LoopJobDispatch);f.hooks.selected.arm(ProgressiveControlTestPoint::LoopJobSelected);
    progressive::LoopOptions keep;keep.startPolicy=progressive::LoopStartPolicy::KeepPosition;
    const auto loop=f.engine->requestLoopRange(0,f.inputFrames,f.context(),keep);require(loop.accepted,"F01 KeepPosition受付拒否");f.loopID=loop.id;
    f.until([&]{return f.hooks.dispatch.entered.load();},"F01選択前dispatch窓未捕捉");
    if(checkpointFailure)f.until([&]{return f.checkpoint.failHits.load()==1&&f.engine->getPlaybackDiagnostics().pipeline.loopReuse.normalPreparation==ph58::NormalLoopReuseState::LimitReached;},"F01実normal checkpoint permit拒否未到達");
    s.old=f.request("F01_A_75_before_job_selection",.75);require(f.row(s.old.id).state==LS::Pending,"F01選択前AがPendingでない");
    f.release(f.hooks.dispatch);f.until([&]{return f.hooks.selected.entered.load();},"F01構築済みjobの最初のmutex解放窓未捕捉");
    const auto selected=f.engine->getLoopSnapshot();const auto d=f.engine->getPlaybackDiagnostics();s.beforeLatest=f.row(s.old.id);
    s.selectedNs=selected.lastPreparationNs;s.selectedCount=selected.preparationCount;s.selectedVersion=s.beforeLatest.preparationVersion;s.published=d.pipeline.published;s.consumed=d.pipeline.consumed;
    require(selected.enabled&&!selected.reusable&&!selected.initialPositionComplete&&selected.speedRequestID==s.old.id&&selected.preparationCount==1&&selected.lastPreparationNs&&
            d.session==f.normalContext.session&&s.published>=s.consumed&&!f.capture.firstNewSession.load(),"F01初回job/正常owner/未採用の選択条件不成立");
    if(checkpointFailure)require(f.checkpoint.failHits==1&&f.checkpoint.failedSession==f.normalContext.session&&!f.checkpoint.armed,"F01実permit拒否のowner不一致");
    else require(d.pipeline.dspDone,"F01選択後に短曲dspDoneを失った");
    s.latest=f.request("F01_B_200_after_job_selection_before_start",2.);s.afterLatest=f.row(s.old.id);const auto latest=f.row(s.latest.id);
    require(!s.beforeLatest.committed&&!s.beforeLatest.outputStarted&&!s.beforeLatest.firstPcmObservedNs&&!s.beforeLatest.adoptionPending&&
            !s.afterLatest.committed&&!s.afterLatest.outputStarted&&!s.afterLatest.firstPcmObservedNs&&!s.afterLatest.adoptionPending&&
            !latest.committed&&!latest.outputStarted&&!latest.firstPcmObservedNs&&!latest.adoptionPending,"F01 next開始前に未発生のcommit/PCM事実を記録した");
    s.latestAfterAccept=latest;return s;
}
void saveSelectedWindow(ReviewFixture& f,const SelectedSupply& s){
    // 小さい証拠ファイルでも、旧FIFOの準備余裕を消費しないようgate解放後に保存する。
    std::ofstream window(f.folder/"F01_selected_window.json");window<<"{\"hook\":\"LoopJobSelected\",\"engine_mutex_held\":false,\"next_constructed\":true,\"next_started\":false,\"callback_gate\":false,\"input_generation\":"<<f.normalContext.inputGeneration
        <<",\"normal_session\":"<<f.normalContext.session<<",\"normal_epoch\":"<<f.normalContext.renderEpoch<<",\"loop_ID\":"<<f.loopID<<",\"input_B\":"<<f.inputFrames<<",\"selected_preparing_ns\":"<<s.selectedNs
        <<",\"selected_preparation_count\":"<<s.selectedCount<<",\"external_preparation_version\":"<<s.selectedVersion<<",\"normal_published\":"<<s.published<<",\"normal_consumed\":"<<s.consumed
        <<",\"checkpoint_failure_hits\":"<<f.checkpoint.failHits.load()<<",\"A_before_B\":"<<operationJson(s.beforeLatest)<<",\"A_after_B\":"<<operationJson(s.afterLatest)<<",\"B_after_accept\":"<<operationJson(s.latestAfterAccept)<<"}\n";
    require(bool(window),"F01選択窓の証拠保存失敗");
}
void selectedSupplyIdentity(ReviewFixture& f,bool checkpointFailure){
    normalWithoutSelfRepeat(f,checkpointFailure);f.pass("F01.normal_no_self_repeat_condition");const auto selected=selectInitialSupply(f,checkpointFailure);f.pass("F01.selected_job_then_latest_B_window");
    const bool protectedBeforeOutput=selected.beforeLatest.state==LS::Preparing&&selected.beforeLatest.preparingNs&&selected.beforeLatest.preparationVersion&&
        selected.beforeLatest.inputGeneration==f.normalContext.inputGeneration&&selected.beforeLatest.sourceSession==f.normalContext.session&&!progressive::terminal(selected.afterLatest.state);
    f.release(f.hooks.selected);saveSelectedWindow(f,selected);
    f.until([&]{const auto events=f.engine->loopHistory();return f.capture.firstNewSession.load()&&!events.empty()&&events.front().oldOutputEnd==f.inputFrames&&events.front().callbackFrame==f.inputFrames;},"F01実初回B/新session/PCM未観測");
    const auto first=f.engine->loopHistory().front();const auto actualSession=f.capture.firstNewSession.load();
    const auto raw=f.capture.native.observed[first.newEpoch%64].read();
    require(first.loopID==f.loopID&&first.settingCycle==1&&first.inputA==0&&first.inputBExclusive==f.inputFrames&&!first.overlapFrames&&
            raw&&raw->generation==f.normalContext.inputGeneration&&raw->session==actualSession&&raw->epoch==first.newEpoch&&raw->end>raw->firstAt&&f.capture.sawSession(actualSession),"F01実初回Bの入力世代/周回/RAW/session/epoch不一致");
    f.until([&]{return progressive::terminal(f.row(selected.old.id).state);},"F01採用後Aの終端期限");const auto adopted=f.row(selected.old.id);const auto past=operationJson(adopted);f.saveLedger("F01_after_initial_B_ledger.jsonl");f.pass("F01.actual_initial_B_session_epoch_PCM");
    const auto latest=f.completed(selected.latest.id);f.actualPcm(latest);require(f.engine->getStateSnapshot().appliedTargetSpeed==2.&&operationJson(f.row(selected.old.id))==past,"F01最新Bの適用またはA過去履歴不変に失敗");f.pass("F01.latest_B_Completed_and_A_past_immutable");
    // 旧比較版でも実A採用とBの終端まで観測してから、この整合checkをFAILにする。
    // A Replacedだけ、装置停止、窓未捕捉、B期限超過は再現成功として扱わない。
    const bool matching=protectedBeforeOutput&&adopted.state==LS::Completed&&adopted.session==actualSession&&adopted.renderEpoch==first.newEpoch&&adopted.outputStarted&&adopted.firstPcmObservedNs&&adopted.completedNs;
    std::ofstream adoption(f.folder/"F01_actual_adoption.json");adoption<<"{\"old_external_ID\":"<<selected.old.id<<",\"latest_external_ID\":"<<selected.latest.id<<",\"input_generation\":"<<f.normalContext.inputGeneration
        <<",\"loop_ID\":"<<f.loopID<<",\"selected_preparation_count\":"<<selected.selectedCount<<",\"selected_preparing_ns\":"<<selected.selectedNs<<",\"actual_initial_B_callback_frame\":"<<first.callbackFrame
        <<",\"actual_old_epoch\":"<<first.oldEpoch<<",\"actual_A_session\":"<<actualSession<<",\"actual_A_epoch\":"<<first.newEpoch<<",\"actual_A_RAW_first\":"<<raw->firstAt<<",\"actual_A_RAW_end\":"<<raw->end
        <<",\"actual_A_RAW_observed\":true,\"actual_initial_setting_cycle\":"<<first.settingCycle<<",\"protected_before_output\":"<<(protectedBeforeOutput?"true":"false")
        <<",\"A_identity_matches_adoption\":"<<(matching?"true":"false")<<",\"A_past_immutable_after_B\":true,\"A_after_actual_adoption\":"<<operationJson(adopted)<<",\"B_Completed\":"<<operationJson(latest)<<"}\n";
    adoption.flush();require(bool(adoption),"F01実採用の証拠保存失敗");f.saveLedger("F01_after_B_ledger.jsonl");
    require(matching,"F01: 初回Bで実際に採用したAが保護済みCompletedでなく、外部要求IDと実PCMが不一致");f.actualPcm(adopted);f.pass("F01.required_A_protected_and_Completed");
    f.exactIds({LS::Completed,LS::Completed});f.saveLedger("terminal_ledger.jsonl");f.pass("F01.exact_IDs_and_terminal_types");
    require(f.engine->getPlaybackDiagnostics().pipeline.loopReuse.checkpointPeak<=2,"F01 checkpoint上限超過");f.qualityAndOwnership();f.pass("normal_supply_heap_owner_audit");
}

void selectedSupplyCancellation(ReviewFixture& f,const std::string& mode,const std::filesystem::path& input){
    normalWithoutSelfRepeat(f,true);const auto selected=selectInitialSupply(f,true);f.pass("F01_CANCEL.normal_no_self_repeat_and_selected_A");
    require(selected.beforeLatest.state==LS::Preparing&&selected.beforeLatest.preparationVersion&&!progressive::terminal(selected.afterLatest.state),"F01補助試験で選択済みAを保護できない");f.pass("F01_CANCEL.latest_B_accepted_no_false_facts");
    const bool stop=mode=="f01_selected_stop",clear=mode=="f01_selected_clear";std::vector<LS> terminal{stop||clear?LS::Cancelled:LS::Failed,LS::Cancelled,LS::Completed};
    if(stop){
        std::exception_ptr error;std::atomic<bool> returned{false};
        std::jthread action([&]{try{f.engine->stop();}catch(...){error=std::current_exception();}returned=true;});
        f.atomicUntil([&]{return f.hooks.selected.cleanupWait.load();},"F01選択直後Stopの取消完了窓未到達");f.hooks.selected.released=true;
        f.atomicUntil([&]{return returned.load();},"F01選択直後Stopのjoin期限");action.join();if(error)std::rethrow_exception(error);require(f.engine->getPlaybackState()==State::Stopped,"F01選択直後Stopが停止しない");
    }else if(clear){
        const auto receipt=f.engine->requestClearLoop(f.loopID,f.context());require(receipt.accepted&&!f.engine->getLoopSnapshot().enabled,"F01選択直後Clear受付拒否");f.release(f.hooks.selected);
        f.until([&]{return !f.engine->getLoopSnapshot().clearPending&&f.engine->getPlaybackState()==State::Ended;},"F01選択直後Clearの全曲EOF継続期限");
    }else{
        f.checkpoint.failNewWorkgroup=true;f.hooks.selected.released=true;
        f.atomicUntil([&]{return f.engine->getPlaybackState()==State::Failed;},"F01公開前の実準備失敗が安全停止へ到達しない",20);
        require(f.checkpoint.workgroupFailureHits==1&&f.checkpoint.workgroupFailureSession&&f.checkpoint.workgroupFailureSession!=f.normalContext.session,"F01実Workgroup準備失敗のowner/回数不一致");
        f.engine->stop();
    }
    if(!stop)f.engine->stop();saveSelectedWindow(f,selected);
    require(!f.capture.firstNewSession.load()&&!f.capture.newSourceFrames.load(),"F01未採用の取消/失敗版からPCMを出力した");
    for(std::size_t i=0;i<2;++i){const auto op=f.row(f.ids[i]);require(op.state==terminal[i]&&!op.reason.empty()&&!op.committed&&!op.outputStarted&&!op.firstPcmObservedNs&&!op.completedNs,"F01取消/失敗したIDの終端理由または未採用事実が不正");}
    require(!f.engine->getLoopSnapshot().enabled&&!ph58::RealtimePipeline::executionOwnerCounts().alive,"F01取消/失敗後のLoop/owner残存");f.saveLedger("F01_after_action_ledger.jsonl");f.pass("F01_CANCEL.action_effective_no_A_or_B_PCM");
    // 再prepareは公開APIで行い、新しい入力世代とLoopで次の速度要求が進むことを確認する。
    // callback座標は新音声構成で0から始まるため、旧構成の監査値を先に確定保存してから監査器を再初期化する。
    const auto oldDiagnostics=f.engine->getPlaybackDiagnostics();require(!oldDiagnostics.missingFrames&&!oldDiagnostics.underrunCalls&&!oldDiagnostics.rejectedWrites&&!f.capture.native.audit.errors&&!f.capture.native.audit.nonfinite,"F01取消/故障注入前後の供給/PCM監査失敗");
    std::ofstream phase(f.folder/"F01_action_cleanup.json");phase<<"{\"action\":"<<ph58::jsonString(mode)<<",\"input_generation\":"<<f.normalContext.inputGeneration<<",\"A\":"<<operationJson(f.row(selected.old.id))<<",\"B\":"<<operationJson(f.row(selected.latest.id))
        <<",\"owners_alive\":0,\"callback_gate\":false,\"missing\":"<<oldDiagnostics.missingFrames<<",\"workgroup_failure_hits\":"<<f.checkpoint.workgroupFailureHits.load()<<",\"workgroup_failure_session\":"<<f.checkpoint.workgroupFailureSession.load()<<",\"old_PCM_audit_errors\":0,\"old_PCM_nonfinite\":0}\n";require(bool(phase),"F01取消後監査保存失敗");
    f.capture.native.audit=LoopPcmAudit(ts::WavStreamReader(input).channels());
    require(f.engine->prepare(input,f.options),"F01取消/失敗後のprepare拒否");f.until([&]{return f.engine->getPlaybackState()==State::Ready;},"F01取消/失敗後の通常Ready期限");
    require(f.context().inputGeneration!=f.normalContext.inputGeneration,"F01再prepareで入力世代が更新されない");const auto loop=f.engine->requestLoopRange(0,f.inputFrames,f.context());require(loop.accepted,"F01取消/失敗後の新Loop受付拒否");f.loopID=loop.id;
    f.until([&]{return f.engine->getLoopSnapshot().initialPositionComplete&&!f.engine->getPlaybackDiagnostics().retiringPipeline;},"F01取消/失敗後のLoop準備/退役期限");
    const auto recovery=f.request("F01_recovery_125_after_selected_job_retired",1.25);f.until([&]{return f.row(recovery.id).state==LS::ReadyForResume;},"F01取消/失敗後の最新速度ReadyForResume期限");
    require(f.engine->play(),"F01取消/失敗後の明示Play拒否");const auto recovered=f.completed(recovery.id);f.actualPcm(recovered);f.exactIds(terminal);f.saveLedger("terminal_ledger.jsonl");f.pass("F01_CANCEL.prepared_owner_joined_and_followup_recovers");
    f.qualityAndOwnership();f.engine.reset();require(f.finalAudit.complete(),"F01直接close後のFinalLoopSpeedAudit未完了");f.finalAudit.save(f.folder/"final_close_ledger.jsonl");
    std::set<std::uint64_t> actual,wanted(f.ids.begin(),f.ids.end());for(const auto& op:f.finalAudit.operations){require(actual.insert(op.id).second&&progressive::terminal(op.state),"F01直接close監査のID重複/未終端");const auto at=std::find(f.ids.begin(),f.ids.end(),op.id);require(at!=f.ids.end()&&op.state==terminal[std::size_t(at-f.ids.begin())],"F01直接close監査の終端種別不一致");if(op.state!=LS::Completed)require(!op.reason.empty()&&!op.outputStarted&&!op.firstPcmObservedNs,"F01直接close監査の取消/失敗理由不正");}
    require(actual==wanted,"F01直接close監査の受付ID集合不一致");f.pass("F01_CANCEL.direct_close_exact_IDs_reasoned_terminal");f.pass("normal_supply_heap_owner_audit");
}

void initialSupplyClearStarted(ReviewFixture& f){
    require(f.inputFrames==f.rate,"A2 Clear競合は正確に1秒の全曲入力を使う");
    f.playNormal();require(!f.engine->getPlaybackDiagnostics().pipeline.dspDone,"保存点失敗前に通常producerが終了済み");
    f.checkpoint.targetSession=f.normalContext.session;f.checkpoint.armed=true;
    const auto old=f.bindInitial(progressive::LoopStartPolicy::KeepPosition,f.inputFrames,false,true);
    const auto loop=f.engine->getLoopSnapshot();const auto before=f.row(old.id);
    require(f.checkpoint.failHits.load()==1&&f.checkpoint.failedSession.load()==f.normalContext.session&&!f.checkpoint.armed&&
            f.engine->getPlaybackDiagnostics().pipeline.loopReuse.normalPreparation==ph58::NormalLoopReuseState::LimitReached&&
            !loop.reusable&&!f.capture.firstNewSession.load()&&before.state==LS::Preparing&&!before.committed&&!before.outputStarted,
            "実permit失敗/自己反復無効/未採用の旧75準備版の条件不成立");
    f.pass("A2_CLEAR.real_CheckpointPermit_failure_initial75_bound");
    const auto latest=f.request("latest_200_waits_initial75_before_Clear",2.);const auto retained=f.row(old.id);const auto pending=f.row(latest.id);
    require(f.ids.size()==2&&f.engine->getLoopSnapshot().speedRequestID==latest.id&&
            !progressive::terminal(retained.state)&&!retained.committed&&!retained.outputStarted&&!retained.firstPcmObservedNs&&!retained.adoptionPending&&
            !progressive::terminal(pending.state)&&!pending.committed&&!pending.outputStarted&&!pending.firstPcmObservedNs,
            "初回75供給版/最新200待機を区別できない、または未発生の採用事実あり");
    f.saveLedger("before_Clear_ledger.jsonl");f.pass("A2_CLEAR.latest200_waits_required75_without_false_facts");

    // 公開済みhandoffのworkerはmutex外で待機中。Clearの取消CAS直前だけ
    // engine mutex内で実callbackのB採用を待ち、callback自体は一切止めない。
    f.hooks.decisionPoint=ProgressiveControlTestPoint::ClearCancellationDecision;
    f.hooks.decisionMode=DecisionMode::StartedWins;f.hooks.decisionArmed=true;
    const auto clearContext=f.context();const auto clear=f.engine->requestClearLoop(f.loopID,clearContext);
    require(clear.accepted&&f.hooks.decisionEntered&&!f.hooks.decisionHadPcmBefore&&!f.hooks.decisionExpired&&
            f.hooks.decisionPcmSession.load()&&f.hooks.decisionPcmFrames.load()&&
            f.hooks.decisionPcmSession.load()==f.capture.firstNewSession.load(),
            "Requested取消CAS前のClear窓と、その間の実B採用を確定できない");
    const auto afterDecision=f.row(old.id);const auto continuation=f.row(latest.id);const auto clearing=f.engine->getLoopSnapshot();
    require(!progressive::terminal(afterDecision.state)&&afterDecision.state!=LS::Replaced&&afterDecision.outputStarted&&afterDecision.firstPcmObservedNs&&
            afterDecision.session==f.hooks.decisionPcmSession.load()&&!afterDecision.committed&&
            !progressive::terminal(continuation.state)&&continuation.clearContinuation&&!continuation.outputStarted&&!continuation.firstPcmObservedNs&&
            !clearing.enabled&&clearing.clearPending,
            "Startedが勝った旧75を取消した、または最新200のClear継続移管を失った");
    {
        std::ofstream observation(f.folder/"Clear_cancellation_window.json");observation<<"{\"old_external_ID\":"<<old.id<<",\"latest_external_ID\":"<<latest.id<<",\"loop_ID\":"<<f.loopID
            <<",\"normal_session\":"<<f.normalContext.session<<",\"checkpoint_failed_session\":"<<f.checkpoint.failedSession.load()<<",\"checkpoint_failure_hits\":"<<f.checkpoint.failHits.load()
            <<",\"decision_point\":\"ClearCancellationDecision\",\"Requested_before_hook\":true,\"new_PCM_before_decision\":false,\"new_PCM_session_during_decision\":"<<f.hooks.decisionPcmSession.load()
            <<",\"new_PCM_frames_during_decision\":"<<f.hooks.decisionPcmFrames.load()<<",\"decision_expired\":false,\"callback_gate\":false,\"old_after_decision\":"<<operationJson(afterDecision)
            <<",\"latest_after_decision\":"<<operationJson(continuation)<<"}\n";require(bool(observation),"Clear取消競合の観測保存失敗");
    }
    f.pass("A2_CLEAR.Requested_Clear_cancellation_window");f.release(f.hooks.published);
    const auto adopted=f.completed(old.id);f.actualPcm(adopted);
    require(adopted.session==f.hooks.decisionPcmSession.load()&&adopted.fixedBoundary&&!adopted.committed,"実初回B採用と旧75の固定Completedが不一致");
    f.until([&]{const auto events=f.engine->loopHistory();return !events.empty()&&events.front().oldOutputEnd==f.inputFrames&&events.front().callbackFrame==f.inputFrames&&
            events.front().inputA==0&&events.front().inputBExclusive==f.inputFrames&&!events.front().overlapFrames&&events.front().newEpoch==adopted.renderEpoch;},"Clear競合で旧75の実初回B座標/採用epochを失った");
    const auto oldPast=operationJson(adopted);f.pass("A2_CLEAR.Started_wins_old75_Completed_actual_PCM");

    // 全曲B=EOFの固定Exact継続にはPCMがない。同じ最新IDを追跡し、
    // 実PCM Completedを捏造せず、自然EOF後の理由付きCancelledを要求する。
    f.until([&]{return progressive::terminal(f.row(latest.id).state);},"最新200のClear/EOF終端期限");const auto final=f.row(latest.id);
    f.until([&]{return f.engine->getPlaybackState()==State::Ended&&!f.engine->getLoopSnapshot().clearPending;},"Clearの空EOF継続が自然終了しない");
    require(final.state==LS::Cancelled&&final.clearContinuation&&!final.reason.empty()&&!final.committed&&!final.outputStarted&&!final.firstPcmObservedNs&&!final.completedNs&&!final.noChange,
            "PCMのない最新200 Clear継続が正しくCancelledにならない");
    require(final.session&&final.session!=adopted.session&&!f.capture.sawSession(final.session),"空EOF継続のsessionが欠落または実PCMを誤観測");
    require(!f.engine->getLoopSnapshot().enabled&&operationJson(f.row(old.id))==oldPast,"Clear後のLoop復活または旧75の確定履歴変更");
    {
        std::ofstream eof(f.folder/"Clear_EOF_continuation.json");eof<<"{\"old_75_external_ID\":"<<old.id<<",\"latest_200_external_ID\":"<<latest.id<<",\"input_B_equals_EOF\":"<<f.inputFrames
            <<",\"continuation_scope\":\"ExplicitFixedExactClearAtEOF\",\"old_75_Completed_by_actual_PCM\":true,\"latest_200\":"<<operationJson(final)
            <<",\"continuation_PCM_observed\":false,\"natural_state\":\"Ended\",\"explicit_Stop_before_verdict\":false}\n";require(bool(eof),"Clear EOF継続の証拠保存失敗");
    }
    f.pass("A2_CLEAR.latest200_Clear_EOF_Cancelled_without_PCM");f.exactIds({LS::Completed,LS::Cancelled});f.saveLedger("terminal_ledger.jsonl");
    const auto latestPast=operationJson(final);require(operationJson(f.row(old.id))==oldPast,"終端監査が旧75を変更した");f.pass("A2_CLEAR.exact_IDs_terminal_types_and_past_immutable");
    f.qualityAndOwnership();require(operationJson(f.row(old.id))==oldPast&&operationJson(f.row(latest.id))==latestPast,"最終StopがClear/EOFの確定履歴を変更した");f.pass("normal_supply_heap_owner_audit");
}

std::string internalJson(const rev59::SpeedOperation& op){
    std::ostringstream out;out<<"{\"id\":"<<op.id<<",\"session\":"<<op.session<<",\"input_generation\":"<<op.inputGeneration<<",\"target\":"<<op.target<<",\"state\":"<<ph58::jsonString(rev59::name(op.state))<<",\"acceptance\":"<<int(op.acceptance)<<",\"applied_s\":"<<op.appliedS<<",\"completed_s\":"<<op.completedS<<'}';return out.str();
}
void internal4096(ReviewFixture& f){
    require(f.inputFrames>=std::uint64_t(f.rate)*90,"実4096件は90秒以上の入力が必要");f.playNormal();std::ofstream requests(f.folder/"internal_receipts.jsonl");std::vector<std::uint64_t> internalIDs;internalIDs.reserve(4096);
    for(std::size_t index=0;index<4096;++index){
        const auto c=f.context();require(c.session==f.normalContext.session&&c.inputGeneration==f.normalContext.inputGeneration,"4096蓄積中にowner/入力が変化");
        const auto r=f.engine->setSpeed(1.,c.session,c.inputGeneration,c.renderEpoch);requests<<"{\"index\":"<<index<<",\"id\":"<<r.id<<",\"receipt\":"<<int(r.result)<<",\"session\":"<<c.session<<"}\n";
        require(r.result==InternalResult::Accepted&&r.id==index+1,"同値通常要求が内部レコードを新規受付しなかった");internalIDs.push_back(r.id);
        f.until([&]{const auto ops=f.engine->operationHistory();return ops.size()==index+1&&ops.back().id==r.id&&ops.back().state==rev59::OperationState::Duplicate;},"各内部要求のDuplicate確定期限",5);
    }
    require(bool(requests)&&internalIDs.size()==4096,"内部4096 receipt保存/件数失敗");requests.close();f.pass("B.normal_Playing_same_owner_4096_Duplicate");
    const auto before=f.engine->operationHistory();require(before.size()==4096&&f.engine->loopSpeedHistory().empty(),"外部履歴と内部4096が混同された");
    std::ofstream frozen(f.folder/"internal_4096_before.jsonl");std::vector<std::string> exact;exact.reserve(before.size());
    for(std::size_t i=0;i<before.size();++i){const auto& op=before[i];require(op.id==internalIDs[i]&&op.session==f.normalContext.session&&op.inputGeneration==f.normalContext.inputGeneration&&op.target==1000000&&op.state==rev59::OperationState::Duplicate&&op.acceptance==InternalResult::Duplicate&&op.appliedS<0,"内部全件のID/owner/Duplicate/非採用条件不一致");exact.push_back(internalJson(op));frozen<<exact.back()<<'\n';}require(bool(frozen),"内部全件保存失敗");frozen.close();f.pass("B.all_internal_records_exact_and_no_Accepted_history");
    f.until([&]{return f.engine->getPlaybackDiagnostics().pipeline.analysisDone;},"Keep前の最終解析期限");
    // 自己反復Readyを先に確定し、初回供給jobが同速度NoOpへ進む条件を固定する。
    f.hooks.dispatch.arm(ProgressiveControlTestPoint::LoopJobDispatch);
    progressive::LoopOptions keep;keep.startPolicy=progressive::LoopStartPolicy::KeepPosition;const auto l=f.engine->requestLoopRange(0,f.inputFrames,f.context(),keep);require(l.accepted,"内部4096後のKeep受付拒否");f.loopID=l.id;
    f.until([&]{return f.hooks.dispatch.entered.load();},"Keep初回job選択前hook未到達");
    f.until([&]{const auto d=f.engine->getPlaybackDiagnostics();return d.session==f.normalContext.session&&d.pipeline.loopReuse.normalPreparation==ph58::NormalLoopReuseState::Ready&&f.engine->getLoopSnapshot().reusable;},"job選択前の通常owner自己反復Ready期限");
    f.release(f.hooks.dispatch);
    f.until([&]{const auto d=f.engine->getPlaybackDiagnostics();const auto loop=f.engine->getLoopSnapshot();return d.session==f.normalContext.session&&d.pipeline.loopReuse.normalPreparation==ph58::NormalLoopReuseState::Ready&&loop.reusable&&loop.initialPositionComplete&&!d.retiringPipeline&&ph58::RealtimePipeline::executionOwnerCounts().alive==1;},"同じownerのKeep自己反復Ready期限");
    require(f.engine->operationHistory().size()==4096&&f.engine->loopSpeedHistory().empty(),"Keep自己反復で台帳が置換された");f.pass("B.Keep_same_owner_self_repeat_Ready");
    const auto preparationCount=f.engine->getLoopSnapshot().preparationCount;const auto preparedRetired=f.engine->getPlaybackDiagnostics().archivedPreparedEpochCount;const auto r=f.request("external_75_at_internal4096",.75);
    f.until([&]{return progressive::terminal(f.row(r.id).state);},"内部上限の外部終端期限");const auto failed=f.row(r.id);
    require(failed.state==LS::Failed&&failed.deferral==progressive::LoopSpeedDeferral::InternalLimit&&failed.reason.find("内部動的要求台帳")!=std::string::npos&&failed.readyNs&&!failed.dynamicOperationID&&!failed.outputStarted&&!failed.committed,"実内部LimitReachedがFailed/InternalLimitへ伝播しない");f.pass("B.external_Accepted_then_real_InternalLimit_Failed");
    f.until([&]{const auto d=f.engine->getPlaybackDiagnostics();return !d.retiringPipeline&&d.archivedPreparedEpochCount>preparedRetired&&ph58::RealtimePipeline::executionOwnerCounts().alive==1;},"内部上限後の準備版退役期限");
    const auto frames=f.capture.native.frames.load();f.until([&]{return f.capture.native.frames.load()>=frames+f.rate/5;},"内部上限後の旧PCM継続なし");require(f.context().session==f.normalContext.session&&f.engine->getLoopSnapshot().enabled&&f.engine->getLoopSnapshot().preparationCount>preparationCount,"旧Loopまたは実次版準備を確認できない");
    const auto after=f.engine->operationHistory();require(after.size()==exact.size(),"内部上限が既存履歴件数を変更");std::ofstream kept(f.folder/"internal_4096_after.jsonl");for(std::size_t i=0;i<after.size();++i){const auto value=internalJson(after[i]);require(value==exact[i],"内部上限が既存履歴を変更");kept<<value<<'\n';}require(bool(kept),"内部履歴保存失敗");
    f.pass("B.old_PCM_history_and_preparation_retirement");f.exactIds({LS::Failed});require(f.row(r.id).deferral==progressive::LoopSpeedDeferral::InternalLimit,"最終原因が後から上書きされた");f.saveLedger("terminal_ledger.jsonl");f.pass("B.exact_external_ID_and_final_cause");f.qualityAndOwnership();f.pass("normal_supply_heap_owner_audit");
}

void detectorSelfTest(){
    phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"heap検出器自己試験失敗");phase61_heap_reset();hostCallbackCppNew=0;
}
}

int main(int argc,char** argv){
    if(argc!=6){std::cerr<<"MODE INPUT candidate|baseline NEW_OUTPUT_DIR SOURCE_LIST_SHA256\n";return 2;}
    int result=1;std::thread owner([&]{std::filesystem::path folder;std::unique_ptr<ReviewFixture> f;bool owned=false;const std::string mode=argv[1];std::vector<std::string> expected;
        try{
            expected=reviewChecks(mode);const auto input=std::filesystem::absolute(argv[2]);const std::string preset=argv[3],sourceSha=argv[5];require(preset=="candidate"||preset=="baseline","Preset不正");require(sourceSha.size()==64&&sourceSha.find_first_not_of("0123456789abcdef")==std::string::npos,"ソース一覧SHA-256不正");
            folder=std::filesystem::absolute(argv[4]);require(std::filesystem::create_directories(folder),"既存の出力先へ上書きしない");owned=true;
            std::ofstream manifest(folder/"EXPECTED.json");manifest<<"{\"schema\":1,\"suite\":\"phase62_adoption_review\",\"mode\":"<<ph58::jsonString(mode)<<",\"preset\":"<<ph58::jsonString(preset)<<",\"source_list_sha256\":"<<ph58::jsonString(sourceSha)<<",\"input_sha256\":"<<ph58::jsonString(fileHash(input))<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))<<",\"driver_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::path(__FILE__)))<<",\"expected\":"<<expected.size()<<",\"expected_Accepted_external_IDs\":"<<(mode=="b_internal4096"?1:mode.rfind("f01_selected_",0)==0?3:2)<<",\"expected_internal_Duplicate_records\":"<<(mode=="b_internal4096"?4096:0)<<",\"checks\":[";
            for(std::size_t i=0;i<expected.size();++i)manifest<<(i?",":"")<<ph58::jsonString(expected[i]);manifest<<"],\"callback_gate\":false,\"normal_control_hooks_only\":true,\"independent_DSP\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";require(bool(manifest),"EXPECTED保存失敗");manifest.close();
            detectorSelfTest();f=std::make_unique<ReviewFixture>(input,preset=="candidate"?Preset::Candidate:Preset::Baseline,folder,expected);
            if(mode=="a1_cancel"||mode=="a1_started")adoptionRace(*f,mode=="a1_started");else if(mode=="a2_initial_supply"||mode=="a2_checkpoint_supply")initialSupply(*f,mode=="a2_checkpoint_supply");else if(mode=="a2_clear_started")initialSupplyClearStarted(*f);else if(mode=="f01_dsp_done"||mode=="f01_checkpoint")selectedSupplyIdentity(*f,mode=="f01_checkpoint");else if(mode.rfind("f01_selected_",0)==0)selectedSupplyCancellation(*f,mode,input);else internal4096(*f);
            require(f->passed==expected,"必須check集合/件数不一致");const auto owners=ph58::RealtimePipeline::executionOwnerCounts();std::ofstream summary(folder/"SUMMARY.json");
            summary<<"{\"schema\":1,\"suite\":\"phase62_adoption_review\",\"mode\":"<<ph58::jsonString(mode)<<",\"preset\":"<<ph58::jsonString(preset)<<",\"run_complete\":true,\"status\":\"PASS\",\"expected\":"<<expected.size()<<",\"executed\":"<<f->passed.size()<<",\"Accepted_IDs\":[";
            for(std::size_t i=0;i<f->ids.size();++i)summary<<(i?",":"")<<f->ids[i];summary<<"],\"owner_peak\":"<<owners.peak<<",\"owners_alive\":"<<owners.alive<<",\"callback_cpp_new\":"<<hostCallbackCppNew.load()<<",\"callback_malloc\":"<<phase61_heap_allocations()<<",\"callback_free\":"<<phase61_heap_frees()<<",\"independent_DSP\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"local_overall_go\":false}\n";require(bool(summary),"SUMMARY保存失敗");summary.close();std::ifstream saved(folder/"SUMMARY.json");std::cout<<saved.rdbuf();result=0;
        }catch(const std::exception& error){
            std::cerr<<error.what()<<'\n';if(f){f->hooks.releaseAll();try{if(f->engine){f->engine->stop();f->saveLedger("failure_ledger.jsonl");writePhase62Trace(folder/"failure_callbacks_all_spans.jsonl",f->engine->loopCallbackRecords());}}catch(...){}}
            if(owned){std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"suite\":\"phase62_adoption_review\",\"mode\":"<<ph58::jsonString(mode)<<",\"run_complete\":false,\"status\":\"FAIL\",\"expected\":"<<expected.size()<<",\"executed\":"<<(f?f->passed.size():0)<<",\"reason\":"<<ph58::jsonString(error.what())<<"}\n";}
        }
    });owner.join();return result;
}
