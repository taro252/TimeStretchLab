// D07の下位planner試験。音声出力も実DSP所有者も作らない。
// 640回の取消と、単一plannerに確定した512件の履歴を明確に分ける。
#include "prototype/Phase59ProgressiveTransition.h"
#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
namespace p56=ts::prototype::phase56;
namespace p59=ts::prototype::phase59;
using Planner=p59::ProgressiveTransitionPlanner;
using Frontier=ts::prototype::Phase36StreamingSpeedEngine::Frontier;
constexpr std::uint32_t rate=48000,initialSpeed=1000000,otherSpeed=990000;
constexpr std::uint64_t generation=6207;
constexpr std::size_t frames=8*1024*1024;

void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
template<class F> void rejects(F&& action,const char* why){
    bool rejected=false;try{action();}catch(const std::logic_error&){rejected=true;}
    need(rejected,why);
}
// 過渡イベントのない合成解析。plannerの上限だけを調べるため、WAVや
// 製品PCMから期待Mapを生成せず、Phase56の確定Map構築器をそのまま使う。
std::shared_ptr<const p56::AnalysisSnapshot> snapshot(){
    auto value=std::make_shared<p56::AnalysisSnapshot>();
    value->inputGeneration=generation;value->receivedInputFrames=frames;
    value->featureThrough=frames/1024+1;value->detectorThrough=value->featureThrough;
    value->isFinal=true;
    p56::MapPrefixBuilder builder({initialSpeed});builder.finish(value->featureThrough);
    value->mapThroughNode=builder.nodes[0].size();
    need(value->mapThroughNode>2,"合成解析の確定Mapが不足");
    return value;
}
void fixedStart(const std::shared_ptr<const p56::AnalysisSnapshot>& s,bool candidate){
    Planner planner(rate,frames,generation,initialSpeed,candidate);
    need(planner.historyCount()==0&&!planner.view(),"新しいplannerが履歴を継承");
    planner.update(s);const auto fixed=planner.view();
    need(fixed&&fixed->final&&!fixed->hasTransitions&&fixed->modes.empty()&&
         fixed->baseVersion==0&&fixed->inputGeneration==generation&&
         planner.historyCount()==0&&planner.tail().micros==initialSpeed,
         "最初の確定Mapが履歴なし固定Mapではない");
    p56::MapPrefixBuilder expected({initialSpeed});expected.finish(s->featureThrough);
    need(fixed->map.starts()==expected.nodes[0]&&fixed->outputFrames==frames,
         "最初のMapが指定した固定速度に一致しない");
}
void rollbackProposals(const std::shared_ptr<const p56::AnalysisSnapshot>& s,bool candidate){
    Planner planner(rate,frames,generation,initialSpeed,candidate);planner.update(s);
    const auto fixed=planner.view();std::uint64_t previousProposalVersion=fixed->version;
    Frontier frontier;
    for(std::uint64_t id=1;id<=640;++id){
        const auto result=planner.plan({otherSpeed},id,0,0,frontier);
        need(result.status==p59::PlanningStatus::Decided&&result.change.plan.applied()&&
             !result.limitReached,"取消試験が実際の適用可能proposalへ到達していない");
        const auto proposed=planner.view();
        need(planner.historyCount()==1&&proposed->hasTransitions&&
             proposed->baseVersion==fixed->version&&proposed->version>previousProposalVersion&&
             planner.tail().micros==otherSpeed,"未確定proposalの履歴・版番号が不正");
        previousProposalVersion=proposed->version;
        // 未応答proposalを重ねられないことも、同じ実plannerで確認する。
        if(id==1){
            rejects([&]{planner.plan({initialSpeed},id+1,0,0,frontier);},
                    "未応答proposalへ次のplanを重ねられた");
            rejects([&]{planner.update(s);},"未応答proposal中に解析を更新できた");
        }
        planner.confirmPlan(false);
        need(planner.historyCount()==0&&planner.tail().micros==initialSpeed&&
             planner.view().get()==fixed.get()&&!planner.view()->hasTransitions&&
             planner.view()->modes==fixed->modes&&planner.view()->map.starts()==fixed->map.starts(),
             "取消proposalが履歴・速度・Mapを完全に復元していない");
    }
    rejects([&]{planner.confirmPlan(false);},"取引のないrollbackを受理");
}
void failedPublicationRollback(const std::shared_ptr<const p56::AnalysisSnapshot>& s,bool candidate){
    Planner planner(rate,frames,generation,initialSpeed,candidate);planner.update(s);
    const auto fixed=planner.view();Frontier frontier;bool failed=false;
    planner.injectPublishFailureForTest();
    try{planner.plan({otherSpeed},1,0,0,frontier);}catch(const std::bad_alloc&){failed=true;}
    need(failed&&planner.historyCount()==0&&planner.view().get()==fixed.get()&&
         planner.tail().micros==initialSpeed&&!planner.view()->hasTransitions,
         "Map公開失敗が未確定の動的履歴を残した");
    const auto retry=planner.plan({otherSpeed},2,0,0,frontier);
    need(retry.change.plan.applied()&&planner.historyCount()==1,"公開失敗後に再受付できない");
    planner.confirmPlan(false);
    need(planner.historyCount()==0&&planner.view().get()==fixed.get(),"再受付取消で固定Mapへ戻らない");
}
void onePlannerRealLimit(const std::shared_ptr<const p56::AnalysisSnapshot>& s,bool candidate){
    static_assert(p59::maximumChanges==512,"D07は製品履歴512の変更を許容しない");
    Planner planner(rate,frames,generation,initialSpeed,candidate);planner.update(s);
    std::size_t published=0;std::uint64_t request=0;Frontier frontier;
    // ここだけは同一plannerに全件を確定する。独立した640個のplannerや
    // 取消済みproposalを履歴512への到達として数えない。
    for(std::size_t count=0;count<p59::maximumChanges;++count){
        const auto target=count%2?initialSpeed:otherSpeed;
        frontier.preparedOutput=published;
        const auto result=planner.plan({target},++request,published,published,frontier);
        need(result.status==p59::PlanningStatus::Decided&&result.change.plan.applied()&&
             !result.limitReached,"同一plannerの512件確定試験で途中のplanが拒否された");
        need(planner.historyCount()==count+1&&planner.view()->hasTransitions,
             "単一plannerの動的履歴件数が実際のproposal件数と不一致");
        // 一時的512件目を取消すと511へ戻り、改めて512件目を確定できる。
        if(count+1==p59::maximumChanges){
            planner.confirmPlan(false);
            need(planner.historyCount()==p59::maximumChanges-1,"512件目の取消で枠が戻らない");
            const auto retry=planner.plan({target},++request,published,published,frontier);
            need(retry.change.plan.applied()&&!retry.limitReached&&
                 planner.historyCount()==p59::maximumChanges,"取消後の512件目を再受付できない");
        }
        planner.confirmPlan(true);
        need(planner.historyCount()==count+1&&planner.tail().micros==target,
             "確定後の同一planner履歴が消失");
        published=std::size_t(result.change.plan.completionOutputSample)+4096;
    }
    const auto full=planner.view();const auto tail=planner.tail();
    const auto bytes=planner.mapBytes();frontier.preparedOutput=published;
    const auto refused=planner.plan({otherSpeed},++request,published,published,frontier);
    need(refused.status==p59::PlanningStatus::Decided&&refused.limitReached&&
         refused.change.plan.outcome==ts::prototype::Phase39Outcome::Invalid&&
         !refused.change.plan.applied(),"実512件の次の要求が上限拒否にならない");
    need(planner.historyCount()==512&&planner.view().get()==full.get()&&
         planner.tail().micros==tail.micros&&planner.mapBytes()==bytes,
         "513件目の上限拒否が既存履歴・Map・速度を変更");
    rejects([&]{planner.confirmPlan(false);},"上限拒否が取消可能なproposalを作った");
}
}
int main(){try{
    const auto s=snapshot();std::size_t passed=0;
    for(const bool candidate:{false,true}){
        const std::string preset=candidate?"candidate":"baseline";
        fixedStart(s,candidate);std::cout<<"PASS D07_PLANNER_FIXED_START_"<<preset<<'\n';++passed;
        rollbackProposals(s,candidate);std::cout<<"PASS D07_PLANNER_ROLLBACK_640_"<<preset<<'\n';++passed;
        failedPublicationRollback(s,candidate);std::cout<<"PASS D07_PLANNER_PUBLICATION_ROLLBACK_"<<preset<<'\n';++passed;
        onePlannerRealLimit(s,candidate);std::cout<<"PASS D07_PLANNER_HISTORY_LIMIT_512_"<<preset<<'\n';++passed;
    }
    need(passed==8,"必須IDの実施件数が不足");
    std::cout<<"PHASE62_HISTORY_INVARIANT_COMPLETE expected=8 executed="<<passed
             <<" passed="<<passed<<" lower_planner_only=true loop_exhaustion_reproduced=false\n";
}catch(const std::exception& e){std::cerr<<"FAIL D07 "<<e.what()<<'\n';return 1;}}
