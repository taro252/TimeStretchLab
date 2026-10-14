#pragma once
#include <vector>
#include <string>
#include <cstdint>
#include <limits>
#include <stdexcept>
namespace ts::prototype {
// Control thread only: never used by the audio callback.
struct Phase51Operation {
    std::uint64_t scheduled=0,arrived=0,sent=0,accepted=0,workerSeen=0,ready=0,generation=0;
    std::uint64_t busyBegin=0,busyNs=0,busyPolls=0;
    std::string state="Scheduled";
};
class Phase51CommandControl {
public:
    enum class Policy{Defer,Strict,Continue,Latest};
    static constexpr std::size_t none=std::numeric_limits<std::size_t>::max();
    std::vector<Phase51Operation> operations;
    Policy policy;std::size_t pending=none;bool failed=false;
    explicit Phase51CommandControl(std::size_t count,Policy p):operations(count),policy(p){}
    void arrive(std::size_t i,std::uint64_t now,bool busy) {
        auto& r=operations.at(i);if(r.arrived)throw std::logic_error("Duplicate operation arrival");r.arrived=now;
        if(busy && (policy==Policy::Strict || policy==Policy::Continue)){
            r.state="BusyRejected";r.busyPolls=1;if(policy==Policy::Strict)failed=true;return;
        }
        r.state="Pending";if(busy)r.busyBegin=now;
        if(policy==Policy::Latest){
            if(pending!=none){auto& old=operations[pending];old.state="Replaced";closeBusy(old,now);}
            pending=i;
        }
    }
    std::size_t next(bool ready,std::uint64_t now) {
        if(!ready){for(auto& r:operations)if(r.state=="Pending"){++r.busyPolls;if(!r.busyBegin)r.busyBegin=now;}return none;}
        if(policy==Policy::Latest)return pending;
        for(std::size_t i=0;i<operations.size();++i)if(operations[i].state=="Pending")return i;
        return none;
    }
    void dispatch(std::size_t i,std::uint64_t now){auto& r=operations.at(i);closeBusy(r,now);r.sent=now;r.state="Requested";if(pending==i)pending=none;}
    static void closeBusy(Phase51Operation& r,std::uint64_t now){if(r.busyBegin){r.busyNs+=now-r.busyBegin;r.busyBegin=0;}}
    void stop(std::uint64_t now){for(auto& r:operations)if(r.state=="Pending"||r.state=="Scheduled"||r.state=="Requested"||r.state=="Applied"){closeBusy(r,now);r.state="Stopped";}}
};
}
