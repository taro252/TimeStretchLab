// 制御要約の独立オフライン回帰。音声装置・callbackは使用しない。
// INPUT.wav baseline|candidate NEW_OUTPUT。実行はrootの直列統括で行う。
// SpeedOperationの期待値は旧公開API speedOperations() の全履歴から導く。
// 実適用の1件だけ既存Workgroup経路をarmするが、音声出力は開始しない。
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase45PcmDigest.h"
#include "playback/LoopSpeedLedger.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <vector>

namespace {
namespace fs = std::filesystem;
namespace p58 = ts::prototype::phase58;
namespace p59 = ts::prototype::phase59;
namespace loop = ts::playback::progressive;
using Pipeline = p58::RealtimePipeline;
using Operation = p59::SpeedOperation;
using State = p59::OperationState;
using Receipt = ts::prototype::Phase39RequestResult;
using Clock = std::chrono::steady_clock;

void need(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
std::string quote(const std::string& text) {
    std::string result = "\"";
    for (unsigned char c : text) {
        if (c == '"' || c == '\\') { result += '\\'; result += char(c); }
        else if (c == '\n') result += "\\n";
        else if (c == '\r') result += "\\r";
        else if (c == '\t') result += "\\t";
        else result += c < 32 ? '?' : char(c);
    }
    return result + '"';
}
std::string sha(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    need(bool(stream), "SHA入力がない: " + path.string());
    ts::prototype::Phase45PcmDigest digest;
    std::array<char,65536> block{};
    while (stream.read(block.data(), block.size()) || stream.gcount())
        digest.update(block.data(), std::size_t(stream.gcount()));
    need(stream.eof(), "SHA読取失敗");
    return digest.finish();
}
template<class Predicate> void wait(Pipeline& pipeline, Predicate predicate, const char* why) {
    const auto end = Clock::now() + std::chrono::seconds(30);
    while (!predicate()) {
        need(!pipeline.failed(), pipeline.diagnostics().error);
        need(Clock::now() < end, why);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
void ready(Pipeline& pipeline) {
    pipeline.start();
    need(pipeline.waitUntilReady(std::chrono::seconds(30)), "Ready期限: " + pipeline.diagnostics().error);
}

// paddingをmemcmpしない。履歴と要約に含まれる実値を、全構成要素で比較する。
bool same(const Operation& a, const Operation& b) {
    const auto scalar = [](const Operation& o) {
        return std::tie(o.id,o.session,o.inputGeneration,o.generation,o.target,o.state,o.workerState,o.acceptance,
            o.logicalPresented,o.acceptedLogicalPresented,o.publishedAtPlan,o.consumedAtApply,o.analysisNodesAtPlan,
            o.receivedInputAtPlan,o.planningDecided,o.finalAnalysisAtPlan,o.acceptedS,o.plannerSeenS,o.workerSeenS,
            o.planStartedS,o.planFinishedS,o.appliedS,o.completedS,o.planCpuS,o.planWallS,o.attempts,o.staleReplans,o.analysisDeferrals);
    };
    const auto frontier = [](const Operation& o) {
        const auto& f = o.frontier;
        return std::tie(f.preparedOutput,f.nextInput,f.lastProcessedInput,f.finalizedOla,f.firstUnprocessedFirSource,
            f.recentFrameInput,f.recentFrameOutput,f.recentFrameCount,f.actualWeightSample,f.actualWeight);
    };
    const auto plan = [](const Operation& o) {
        const auto& p = o.change.plan;
        return std::tie(p.outcome,p.requestedFrame,p.appliedFrame,p.rampEndFrame,p.appliedOutputSample,p.completionOutputSample,
            p.protectedEventsSkipped,p.protectedEventsPaused,p.firstMutableFrame,p.firstSafeFrame,p.nextEventFrame,
            p.protectionEndFrame,p.safeFramesUsed,p.heldFrames);
    };
    const auto change = [](const Operation& o) {
        const auto& c = o.change; const auto& r = c.request; const auto& b = c.boundary;
        return std::tie(r.generation,r.target,r.requestedInputSample,r.publishedOutputSample,r.transitionOutputMs,
            b.legacy,b.precise,b.processedNode,b.consumedOla,b.consumedFir,c.outputFrames,c.densityInput,c.statePreserved,c.changesDensity);
    };
    const auto density = [](const Operation& o) {
        const auto& d = o.change.density;
        return std::tie(d.safe,d.inputSample,d.maximumHop,d.maximumHopStep,d.minimumWeight,d.minimumLocalSpeed,d.maximumLocalSpeed,
            d.reconstructedHistoryMismatches,d.reconstructedHistoryMaxDifference,d.actualWeight,d.predictedActualWeight,
            d.weightPredictionAbsoluteError,d.candidatesTried,d.guardWallSeconds,d.guardThreadCpuSeconds);
    };
    if (scalar(a)!=scalar(b) || frontier(a)!=frontier(b) || plan(a)!=plan(b) || change(a)!=change(b) || density(a)!=density(b)) return false;
    const auto& x = a.change.density.candidateTimings; const auto& y = b.change.density.candidateTimings;
    if (x.size()!=y.size()) return false;
    for (std::size_t i=0; i<x.size(); ++i)
        if (std::tie(x[i].inputSample,x[i].accepted,x[i].probed,x[i].wallSeconds,x[i].threadCpuSeconds,x[i].weightCheckSeconds) !=
            std::tie(y[i].inputSample,y[i].accepted,y[i].probed,y[i].wallSeconds,y[i].threadCpuSeconds,y[i].weightCheckSeconds)) return false;
    return true;
}
bool same(const std::optional<Operation>& a, const std::optional<Operation>& b) {
    return bool(a)==bool(b) && (!a || same(*a,*b));
}

// 新索引や新要約の内部処理を期待値には利用しない。旧getterと同じ順方向走査。
p58::SpeedStateSummary derive(const std::vector<Operation>& history) {
    p58::SpeedStateSummary result;
    for (const auto& row : history) {
        if (row.state==State::Pending) result.pending=row;
        else if (row.state==State::Submitted || row.state==State::Applied) result.active=row;
        else result.lastResult=row;
        if (row.appliedS>=0) result.lastAppliedSpeed=row.target;
    }
    return result;
}
bool same(const p58::SpeedStateSummary& a, const p58::SpeedStateSummary& b) {
    return same(a.pending,b.pending) && same(a.active,b.active) && same(a.lastResult,b.lastResult) && a.lastAppliedSpeed==b.lastAppliedSpeed;
}
void summaryMatches(Pipeline& pipeline, const std::vector<Operation>& history) {
    need(same(derive(history),pipeline.speedStateSummary()), "要約が旧全履歴走査と不一致");
}
void progressMatches(Pipeline& pipeline, const std::vector<Operation>& history) {
    need(!pipeline.speedOperationProgress(0) && !pipeline.speedOperationProgress(history.size()+1), "存在しない内部IDを返した");
    for (const auto& row : history) {
        const auto value=pipeline.speedOperationProgress(row.id);
        need(value && value->id==row.id && value->session==row.session && value->appliedS==row.appliedS && value->completedS==row.completedS &&
            value->firstChanged==row.change.plan.appliedOutputSample && value->completion==row.change.plan.completionOutputSample,
            "ID別進捗が旧履歴と不一致");
    }
}
bool copyUnchanged(const ts::playback::ControlCostValue& a, const ts::playback::ControlCostValue& b) {
    return a.calls==b.calls && a.items==b.items && a.objectBytes==b.objectBytes && a.cpuS==b.cpuS && a.wallS==b.wallS;
}
void boundedQueries(Pipeline& pipeline, const std::vector<Operation>& history) {
    const auto before=pipeline.diagnostics();
    const auto expected=derive(history);
    need(before.controlCostsMeasured, "計数無効を0回実測と扱えない");
    for (unsigned n=0; n<128; ++n) {
        need(same(expected,pipeline.speedStateSummary()), "軽量要約が旧全履歴走査と不一致");
        need(pipeline.sessionID()==before.session, "session軽量getter不一致");
        need(pipeline.logicalOutputFrame()==before.consumed, "通常epochの出力座標不一致");
    }
    progressMatches(pipeline,history);
    need(copyUnchanged(before.speedHistoryCopyCost,pipeline.diagnostics().speedHistoryCopyCost), "軽量getterが全履歴コピーを呼んだ");
}
void explicitCopy(Pipeline& pipeline, std::size_t expected) {
    const auto before=pipeline.diagnostics().speedHistoryCopyCost;
    const auto rows=pipeline.speedOperations();
    const auto after=pipeline.diagnostics().speedHistoryCopyCost;
    need(rows.size()==expected && after.calls==before.calls+1 && after.items==before.items+expected &&
        after.objectBytes==before.objectBytes+expected*sizeof(Operation), "明示全履歴コピーのcall/items/bytes計数不一致");
}
bool settled(const Operation& row) { return row.state!=State::Pending && row.state!=State::Submitted && row.state!=State::Applied; }

// 公開LoopSpeedOperationの39実フィールド。paddingや将来の偶然のメモリ配置に依存しない。
auto fields39(const loop::LoopSpeedOperation& o) {
    return std::tie(o.id,o.loopID,o.inputGeneration,o.sourceSession,o.sourceRenderEpoch,o.acceptedCycle,o.speedMicros,o.state,o.deferral,
        o.preparationVersion,o.dynamicOperationID,o.session,o.renderEpoch,o.producerCycle,o.cycle,o.mapVersion,o.outputEnd,o.dynamicSession,o.planningRenderEpoch,
        o.acceptedNs,o.preparingNs,o.readyNs,o.commitObservedNs,o.firstChangedPublishedObservedNs,o.firstPcmObservedNs,o.completedNs,o.terminalNs,
        o.firstChangedOutputFrame,o.completionOutputFrame,o.resumeInputFrame,o.discardedForPausedClearFrames,o.committed,o.outputStarted,o.fixedBoundary,
        o.adoptionPending,o.fixedBoundaryCommitted,o.noChange,o.clearContinuation,o.reason);
}
static_assert(std::tuple_size_v<decltype(fields39(loop::LoopSpeedOperation{}))> == 39);
loop::LoopSpeedOperation populated(std::uint64_t id, loop::LoopSpeedState state) {
    loop::LoopSpeedOperation o;
    o.id=id; o.loopID=7; o.inputGeneration=id+1; o.sourceSession=id+2; o.sourceRenderEpoch=id+3; o.acceptedCycle=id+4;
    o.speedMicros=750000; o.state=state; o.deferral=loop::LoopSpeedDeferral::PreparationDeadline;
    o.preparationVersion=id+5; o.dynamicOperationID=id+6; o.session=42; o.renderEpoch=id+7; o.producerCycle=id+8; o.cycle=id+9;
    o.mapVersion=id+10; o.outputEnd=id+11; o.dynamicSession=id+12; o.planningRenderEpoch=id+13;
    o.acceptedNs=id+14; o.preparingNs=id+15; o.readyNs=id+16; o.commitObservedNs=id+17; o.firstChangedPublishedObservedNs=id+18;
    o.firstPcmObservedNs=id+19; o.completedNs=id+20; o.terminalNs=id+21; o.firstChangedOutputFrame=id+22; o.completionOutputFrame=id+23;
    o.resumeInputFrame=id+24; o.discardedForPausedClearFrames=id+25;
    o.committed=true; o.outputStarted=true; o.fixedBoundary=true; o.adoptionPending=bool(id&1); o.fixedBoundaryCommitted=bool(id&2);
    o.noChange=bool(id&4); o.clearContinuation=true; o.reason="保持すべき終端値"+std::to_string(id);
    return o;
}
void indexMatches(loop::LoopSpeedLedger& ledger) {
    std::vector<std::uint16_t> expected;
    for (std::size_t i=0; i<ledger.records().size(); ++i) {
        const auto s=ledger.records()[i].state;
        if (s!=loop::LoopSpeedState::Completed && s!=loop::LoopSpeedState::Replaced && s!=loop::LoopSpeedState::Cancelled && s!=loop::LoopSpeedState::Failed)
            expected.push_back(std::uint16_t(i));
    }
    const auto actual=ledger.unsettled();
    need(actual.size()==expected.size() && std::equal(actual.begin(),actual.end(),expected.begin()), "未終端索引が独立全履歴走査と不一致");
}

struct Gate {
    std::atomic<bool> armed{false},entered{false},release{false},expired{false};
    std::atomic<std::uint64_t> operation{0};
    static void event(void* context,p58::ControlTestPoint point,std::uint64_t,std::uint64_t id) noexcept {
        auto& g=*static_cast<Gate*>(context);
        if (point!=p58::ControlTestPoint::PlannerBeforePlan || !g.armed.exchange(false)) return;
        g.operation=id; g.entered=true;
        const auto end=Clock::now()+std::chrono::seconds(30);
        while (!g.release.load() && Clock::now()<end) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if (!g.release.load()) g.expired=true;
    }
};
// 例外でもanalysisのゲートを先に解放してから全workerをjoinする。
struct Owner {
    Gate gate;
    std::unique_ptr<Pipeline> pipeline;
    ~Owner() { gate.release=true; if (pipeline) pipeline->stop(); }
};
struct Report {
    fs::path output;
    std::vector<std::string> ids;
    std::set<std::string> seen;
    std::ofstream checks,audit;
    Report(fs::path out,std::vector<std::string> expected) : output(std::move(out)),ids(std::move(expected)) {
        need(!fs::exists(output) && fs::create_directories(output), "新規出力directoryが必要");
        checks.open(output/"checks.jsonl"); audit.open(output/"audit.jsonl");
        need(bool(checks)&&bool(audit),"証拠出力を開けない");
    }
    void pass(const std::string& id) {
        need(std::find(ids.begin(),ids.end(),id)!=ids.end() && seen.insert(id).second,"未宣言/重複ID: "+id);
        checks<<"{\"id\":"<<quote(id)<<",\"pass\":true}\n"; checks.flush(); need(bool(checks),"checks書込失敗");
    }
    void rows(const char* stage,Pipeline& pipeline,const std::vector<Operation>& history) {
        for (const auto& o:history) audit<<std::setprecision(17)<<"{\"stage\":"<<quote(stage)<<",\"id\":"<<o.id<<",\"session\":"<<o.session
            <<",\"state\":"<<quote(p59::name(o.state))<<",\"target\":"<<o.target<<",\"applied_s\":"<<o.appliedS<<",\"completed_s\":"<<o.completedS
            <<",\"first_changed\":"<<o.change.plan.appliedOutputSample<<",\"completion\":"<<o.change.plan.completionOutputSample<<"}\n";
        const auto d=pipeline.diagnostics();
        audit<<"{\"stage\":"<<quote(stage)<<",\"records\":"<<history.size()<<",\"copy_calls\":"<<d.speedHistoryCopyCost.calls
            <<",\"copy_items\":"<<d.speedHistoryCopyCost.items<<",\"copy_bytes\":"<<d.speedHistoryCopyCost.objectBytes
            <<",\"analysis_idle_wakes\":"<<d.analysisIdleWakes<<"}\n"; audit.flush(); need(bool(audit),"audit書込失敗");
    }
    void summary(bool ok,const std::string& reason="") {
        std::ofstream stream(output/"SUMMARY.json");
        stream<<"{\"suite\":\"phase62_control_summary\",\"status\":"<<quote(ok?"PASS":"FAIL")<<",\"expected\":"<<ids.size()
            <<",\"executed\":"<<seen.size()<<",\"passed\":"<<seen.size()<<",\"run_complete\":"<<(ok?"true":"false")
            <<",\"reason\":"<<quote(reason)<<",\"audio_device\":false,\"callback\":false,\"independent_pcm\":false,\"native_getters_exercised\":false}\n";
        stream.flush(); need(bool(stream),"SUMMARY書込失敗");
    }
};
}

int main(int argc,char** argv) {
    std::unique_ptr<Report> report;
    try {
        need(argc==4,"使い方: INPUT.wav baseline|candidate NEW_OUTPUT");
        const std::string preset=argv[2]; need(preset=="baseline"||preset=="candidate","preset不正");
        const std::vector<std::string> ids{
            "L01.four_terminal_states_excluded","L02.terminal_39_fields_immutable","L03.compaction_and_accept_4096",
            "L04.lookup_and_history_retained","L05.overflow_rejected","L06.direct_terminal_compaction",
            "P01.empty_summary","P02.prestart_rejected","P03.invalid_stale_rejected","P04.latest_wins",
            "P05.full_4096_history","P06.limit_no_append","P07.light_getters_no_full_copy","P08.explicit_copy_counter",
            "P09.stop_cancel_and_retention","P10.joined_summary_and_progress",
            "A01.duplicate_summary","A02.submitted_active_pending_latest_result","A03.submitted_queries_no_full_copy",
            "A04.applied_summary_and_progress","A05.applied_queries_no_full_copy","A06.cancel_retains_last_applied",
            "A07.all_workers_joined","F01.input_binary_unchanged"};
        report=std::make_unique<Report>(fs::path(argv[3]),ids); auto& r=*report;
        const auto inputSha=sha(argv[1]),binarySha=sha(fs::absolute(argv[0]));
        {
            std::ofstream expected(r.output/"EXPECTED.json");
            expected<<"{\"suite\":\"phase62_control_summary\",\"expected\":"<<ids.size()<<",\"required_ids\":[";
            for (std::size_t i=0;i<ids.size();++i) expected<<(i?",":"")<<quote(ids[i]);
            expected<<"],\"input_sha256\":"<<quote(inputSha)<<",\"binary_sha256\":"<<quote(binarySha)<<",\"preset\":"<<quote(preset)
                <<",\"history_limit\":4096,\"loop_operation_fields\":39,\"audio_device\":false,\"callback\":false,\"workgroup_arm\":true,\"native_getters_exercised\":false}\n";
            expected.flush(); need(bool(expected),"EXPECTED書込失敗");
        }
        {
            loop::LoopSpeedLedger ledger;
            const std::array terminal{loop::LoopSpeedState::Completed,loop::LoopSpeedState::Replaced,loop::LoopSpeedState::Cancelled,loop::LoopSpeedState::Failed};
            std::vector<loop::LoopSpeedOperation> frozen;
            for (std::size_t i=0;i<terminal.size();++i) { frozen.push_back(populated(i+1,terminal[i]));ledger.accept(frozen.back()); }
            const std::array active{loop::LoopSpeedState::Pending,loop::LoopSpeedState::Preparing,loop::LoopSpeedState::ReadyForResume,
                loop::LoopSpeedState::Committed,loop::LoopSpeedState::FixedBoundaryCommitted,loop::LoopSpeedState::Applied};
            for (std::size_t i=0;i<active.size();++i) ledger.accept(populated(10+i,active[i]));
            indexMatches(ledger); need(ledger.unsettled().size()==6,"未終端6状態のいずれかを除外");r.pass("L01.four_terminal_states_excluded");
            ledger.replaceUnstarted(7,0,900); ledger.cancelUnstarted(7,901,"clear");ledger.cancel(7,902,"stop");ledger.retireEpoch(42,true,903);
            for (const auto& row:frozen) need(!ledger.recordPausedClearDiscard(row.id,row.loopID,row.inputGeneration,row.preparationVersion,999) &&
                fields39(*ledger.find(row.id))==fields39(row),"終端39fieldのいずれかを更新");
            indexMatches(ledger);need(ledger.unsettled().empty(),"取消後の索引に終端が残る");r.pass("L02.terminal_39_fields_immutable");
            for (std::size_t i=ledger.records().size();i<4096;++i) {
                loop::LoopSpeedOperation row; row.id=(std::uint64_t(1)<<63)|(1000+i);row.loopID=8;
                row.state=i%3?loop::LoopSpeedState::Pending:loop::LoopSpeedState::Failed;ledger.accept(row);
                if (i%257==0) indexMatches(ledger);
            }
            indexMatches(ledger);need(ledger.full()&&ledger.records().size()==4096,"4096件保持不一致");r.pass("L03.compaction_and_accept_4096");
            for (const auto& row:ledger.records()) need(ledger.find(row.id)==&row,"ID索引が全履歴本体と不一致");
            need(!ledger.find(0)&&!ledger.find(999999),"未知IDを返した");r.pass("L04.lookup_and_history_retained");
            bool rejected=false;try {loop::LoopSpeedOperation row;row.id=999999;ledger.accept(row);}catch(const std::logic_error&){rejected=true;}
            need(rejected&&ledger.records().size()==4096,"4097件目を保持した");r.pass("L05.overflow_rejected");
            for (const auto& row:ledger.records()) if (row.loopID==8) ledger.find(row.id)->state=terminal[row.id%terminal.size()];
            const auto all=ledger.records();indexMatches(ledger);indexMatches(ledger);
            need(ledger.unsettled().empty()&&all.size()==ledger.records().size(),"直接終端化後の索引不正");
            for(std::size_t i=0;i<all.size();++i) need(fields39(all[i])==fields39(ledger.records()[i]),"圧縮が履歴39fieldを変更");
            r.pass("L06.direct_terminal_compaction");
        }
        p58::Configuration config;config.speedMicros=1000000;config.dynamicTransitions=true;config.scheduling=p58::WorkerScheduling::AudioWorkgroup;
        config.residentInput=true;config.verifyPcm=false;config.candidate=preset=="candidate";config.measureControlCosts=true;
        {
            Owner owner;owner.pipeline=std::make_unique<Pipeline>(argv[1],config);auto& p=*owner.pipeline;
            need(p.inputFrames()>=p.sampleRate()*8ULL,"実適用試験には8秒以上の入力が必要");
            summaryMatches(p,{});progressMatches(p,{});r.pass("P01.empty_summary");
            need(p.requestSpeed(750000,0).result==Receipt::Stopped,"start前を受理");
            auto history=p.speedOperations();summaryMatches(p,history);need(history.size()==1&&history[0].state==State::Rejected,"start前拒否の履歴不正");r.pass("P02.prestart_rejected");
            ready(p);const auto context=p.diagnostics();
            need(p.requestSpeed(405000,0).result==Receipt::Invalid&&p.requestSpeed(750000,0,context.session+1,context.inputGeneration).result==Receipt::Stopped&&
                p.requestSpeed(750000,0,context.session,context.inputGeneration+1).result==Receipt::Stopped,"無効/旧世代を受理");
            history=p.speedOperations();summaryMatches(p,history);need(history.size()==4&&std::all_of(history.begin(),history.end(),[](auto& o){return o.state==State::Rejected;}),"拒否履歴不正");r.pass("P03.invalid_stale_rejected");
            for(auto speed:{750000u,990000u,1250000u}) need(p.requestSpeed(speed,0).result==Receipt::Accepted,"Pending受理失敗");
            history=p.speedOperations();summaryMatches(p,history);
            need(history[4].state==State::Replaced&&history[5].state==State::Replaced&&history[6].state==State::Pending,"最新Pendingへの置換不正");r.pass("P04.latest_wins");
            for(std::size_t i=history.size();i<4096;++i) need(p.requestSpeed(400000u+std::uint32_t(i%161)*10000u,0).result==Receipt::Accepted,"4096以下を拒否");
            history=p.speedOperations();summaryMatches(p,history);
            need(history.size()==4096&&history.back().state==State::Pending&&std::count_if(history.begin(),history.end(),[](auto& o){return o.state==State::Pending;})==1,"4096保持/一枠Pending不正");
            r.rows("full_pending",p,history);r.pass("P05.full_4096_history");
            need(p.requestSpeed(750000,0).result==Receipt::LimitReached&&p.speedOperations().size()==4096,"上限が履歴を増加");r.pass("P06.limit_no_append");
            boundedQueries(p,history);r.pass("P07.light_getters_no_full_copy");explicitCopy(p,4096);r.pass("P08.explicit_copy_counter");
            p.stop();const auto joined=p.speedOperations();summaryMatches(p,joined);
            need(joined.size()==4096&&joined.back().state==State::Cancelled&&std::all_of(joined.begin(),joined.end(),settled),"stop後の取消/全保持不正");
            for(std::size_t i=0;i+1<history.size();++i) need(same(history[i],joined[i]),"stopが既存終端履歴を変更");
            need(p.requestSpeed(750000,0).result==Receipt::Stopped&&p.speedOperations().size()==4096,"停止上限の意味/件数変更");r.pass("P09.stop_cancel_and_retention");
            boundedQueries(p,joined);const auto d=p.diagnostics();need(d.finalDataAvailable&&!d.failed&&!d.scheduling.active,"join最終値不正");r.rows("joined_full",p,joined);r.pass("P10.joined_summary_and_progress");
        }
        {
            Owner owner;auto active=config;active.controlTestHooks={&owner.gate,Gate::event,nullptr};
            owner.pipeline=std::make_unique<Pipeline>(argv[1],active);auto& p=*owner.pipeline;ready(p);
            need(p.inputFrames()>=p.sampleRate()*8ULL,"実適用試験には8秒以上の入力が必要");
            const auto duplicate=p.requestSpeed(1000000,0);need(duplicate.result==Receipt::Accepted&&p.setRealtimeRendering(true),"実制御workerをarmできない");
            wait(p,[&]{const auto s=p.speedStateSummary();return s.lastResult&&s.lastResult->id==duplicate.id&&s.lastResult->state==State::Duplicate;},"同速Duplicate未確定");
            need(p.setRealtimeRendering(false),"Duplicate後の通常policy復元失敗");auto history=p.speedOperations();summaryMatches(p,history);progressMatches(p,history);r.pass("A01.duplicate_summary");
            owner.gate.armed=true;const auto request=p.requestSpeed(750000,0);need(request.result==Receipt::Accepted&&p.setRealtimeRendering(true),"実適用要求/arm失敗");
            wait(p,[&]{return owner.gate.entered.load();},"Submittedゲート未到達");need(owner.gate.operation==request.id,"異なる要求がゲートへ到達");
            const auto pending=p.requestSpeed(1250000,0);need(pending.result==Receipt::Accepted&&p.requestSpeed(405000,0).result==Receipt::Invalid,"並列Pending/拒否作成失敗");
            history=p.speedOperations();summaryMatches(p,history);
            const auto snapshot=p.speedStateSummary();need(snapshot.active&&snapshot.active->id==request.id&&snapshot.active->state==State::Submitted&&
                snapshot.pending&&snapshot.pending->id==pending.id&&snapshot.lastResult&&snapshot.lastResult->state==State::Rejected,"3分類同時保持不正");
            r.rows("submitted_gate",p,history);r.pass("A02.submitted_active_pending_latest_result");boundedQueries(p,history);r.pass("A03.submitted_queries_no_full_copy");
            owner.gate.release=true;
            wait(p,[&]{const auto s=p.speedStateSummary();return s.active&&s.active->id==request.id&&s.active->state==State::Applied&&s.active->appliedS>=0;},"適用ACK未到達（fixtureで安全な区間が必要）");
            need(p.setRealtimeRendering(false),"適用後の通常policy復元失敗");history=p.speedOperations();summaryMatches(p,history);progressMatches(p,history);
            need(derive(history).lastAppliedSpeed==750000&&p.diagnostics().consumed==0,"消費前の適用速度/座標不正");r.rows("applied_paused",p,history);r.pass("A04.applied_summary_and_progress");
            boundedQueries(p,history);r.pass("A05.applied_queries_no_full_copy");
            p.stop();const auto joined=p.speedOperations();summaryMatches(p,joined);progressMatches(p,joined);
            const auto applied=std::find_if(joined.begin(),joined.end(),[&](auto& o){return o.id==request.id;});
            need(applied!=joined.end()&&applied->state==State::Cancelled&&applied->appliedS>=0&&derive(joined).lastAppliedSpeed==750000&&
                std::all_of(joined.begin(),joined.end(),settled),"取消で最終適用速度/履歴を失った");r.rows("joined_applied",p,joined);r.pass("A06.cancel_retains_last_applied");
            boundedQueries(p,joined);const auto d=p.diagnostics();need(d.finalDataAvailable&&!d.failed&&!d.missingFrames&&!d.scheduling.active&&
                d.scheduling.joins==d.scheduling.leaves&&d.scheduling.leaves==d.scheduling.restores&&!owner.gate.expired,"全join/policy復元不正");r.pass("A07.all_workers_joined");
        }
        need(Pipeline::executionOwnerCounts().alive==0,"実行ownerが残った");
        need(sha(argv[1])==inputSha&&sha(fs::absolute(argv[0]))==binarySha,"入力/binaryが実行中に変わった");r.pass("F01.input_binary_unchanged");
        need(r.seen.size()==r.ids.size(),"宣言IDの未実行がある");r.summary(true);
        std::cout<<"PHASE62_CONTROL_SUMMARY_COMPLETE expected="<<ids.size()<<" executed="<<r.seen.size()<<" passed="<<r.seen.size()<<'\n';return 0;
    } catch(const std::exception& error) {
        std::cerr<<"FAIL "<<error.what()<<'\n';if(report)try{report->summary(false,error.what());}catch(...){}return 1;
    }
}
