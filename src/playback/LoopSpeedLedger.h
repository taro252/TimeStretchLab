#pragma once
#include "playback/ProgressiveLoopContract.h"
#include <vector>
#include <stdexcept>
#include <algorithm>
#include <array>
namespace ts::playback::progressive {
// One normal-thread owner (the engine mutex), engine-lifetime retention. No
// callback access, eviction, wraparound, or admission beyond the reserved bound.
class LoopSpeedLedger {
    std::vector<LoopSpeedOperation> records_;
    std::array<std::size_t,8192> index_{}; // bounded identity index, not a second history
    static std::size_t hash(std::uint64_t id)noexcept {return std::size_t((id^(id>>32))*0x9e3779b97f4a7c15ULL)&8191;}
public:
    static constexpr std::size_t maximumOperations=4096;
    LoopSpeedLedger(){records_.reserve(maximumOperations);}
    bool full(std::size_t testLimit=maximumOperations)const noexcept {return records_.size()>=std::min(testLimit,maximumOperations);}
    LoopSpeedOperation* find(std::uint64_t id)noexcept {return const_cast<LoopSpeedOperation*>(static_cast<const LoopSpeedLedger*>(this)->find(id));}
    const LoopSpeedOperation* find(std::uint64_t id)const noexcept {
        for(std::size_t n=0,at=hash(id);n<index_.size();++n,at=(at+1)&8191){const auto slot=index_[at];if(!slot)return nullptr;if(records_[slot-1].id==id)return &records_[slot-1];}return nullptr;
    }
    LoopSpeedOperation& accept(LoopSpeedOperation op){
        if(!op.id||full()||find(op.id))throw std::logic_error("外部Loop速度台帳の予約・IDが不正です");
        const auto id=op.id;records_.push_back(std::move(op));
        for(auto at=hash(id);;at=(at+1)&8191)if(!index_[at]){index_[at]=records_.size();break;}
        return records_.back();
    }
    void replaceUnstarted(std::uint64_t loopID,std::uint64_t except,std::uint64_t now){
        for(auto& op:records_)if(op.loopID==loopID&&op.id!=except&&!terminal(op.state)&&!op.committed&&!op.outputStarted&&!op.adoptionPending){op.state=LoopSpeedState::Replaced;op.terminalNs=now;op.reason="新しい外部速度要求に置換";}
    }
    void cancel(std::uint64_t loopID,std::uint64_t now,const std::string& reason,std::uint64_t keepID=0){
        for(auto& op:records_)if(op.loopID==loopID&&op.id!=keepID&&!terminal(op.state)){
            // Preserve all committed/started facts even when playback stops.
            op.state=LoopSpeedState::Cancelled;op.terminalNs=now;op.reason=reason;
        }
    }
    void cancelUnstarted(std::uint64_t loopID,std::uint64_t now,const std::string& reason,std::uint64_t keepID=0){
        for(auto& op:records_)if(op.loopID==loopID&&op.id!=keepID&&!terminal(op.state)&&!op.committed&&!op.outputStarted&&!op.adoptionPending){op.state=LoopSpeedState::Cancelled;op.terminalNs=now;op.reason=reason;}
    }
    void retireEpoch(std::uint64_t session,bool hadPcm,std::uint64_t now){
        for(auto& op:records_)if(!terminal(op.state)&&op.session==session){
            if((op.fixedBoundary||(!op.dynamicOperationID&&op.readyNs))&&hadPcm){op.state=LoopSpeedState::Completed;op.outputStarted=true;op.firstPcmObservedNs=op.completedNs=op.terminalNs=now;}
            else{op.state=LoopSpeedState::Cancelled;op.terminalNs=now;op.reason="所有者の退役時に未完了の出力適用を終了（開始/commitの事実は保持）";}
        }
    }
    const std::vector<LoopSpeedOperation>& records()const noexcept {return records_;}
};
}
