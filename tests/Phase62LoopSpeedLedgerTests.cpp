#include "playback/LoopSpeedLedger.h"
#include <iostream>
using namespace ts::playback::progressive;
void require(bool value){if(!value)throw std::runtime_error("台帳の不変条件に違反");}
int main(){
    LoopSpeedLedger ledger;LoopSpeedOperation op;op.id=1;op.loopID=7;ledger.accept(op);
    op.id=(std::uint64_t(1)<<63)|1;ledger.accept(op);
    require(ledger.find(1)&&ledger.find(op.id)&&!ledger.find(0));
    ledger.find(1)->committed=true;ledger.find(1)->state=LoopSpeedState::Committed;
    ledger.replaceUnstarted(7,0,2);require(ledger.find(1)->state==LoopSpeedState::Committed);
    require(ledger.find(op.id)->state==LoopSpeedState::Replaced);
    op.id=3;op.outputStarted=true;op.state=LoopSpeedState::ReadyForResume;ledger.accept(op);
    ledger.replaceUnstarted(7,0,3);require(ledger.find(3)->state==LoopSpeedState::ReadyForResume);
    require(ledger.full(3)&&!ledger.full());
    for(std::size_t i=ledger.records().size();i<4096;++i){op={};op.id=100+i;op.loopID=7;ledger.accept(op);}
    require(ledger.full()&&ledger.records().size()==4096);
    bool refused=false;try{op.id=99999;ledger.accept(op);}catch(const std::logic_error&){refused=true;}require(refused&&ledger.records().size()==4096);
    ledger.cancel(7,4,"Stop");for(const auto& item:ledger.records())require(terminal(item.state));
    require(ledger.find(1)->committed&&ledger.find(3)->outputStarted);
    LoopSpeedLedger retired;op={};op.id=1;op.loopID=8;op.session=42;op.readyNs=2;op.outputStarted=true;op.state=LoopSpeedState::ReadyForResume;retired.accept(op);
    retired.retireEpoch(42,false,5);require(retired.find(1)->state==LoopSpeedState::Cancelled&&retired.find(1)->outputStarted);
    op.id=2;op.session=43;op.fixedBoundary=true;retired.accept(op);retired.retireEpoch(43,true,6);require(retired.find(2)->state==LoopSpeedState::Completed);
    LoopSpeedLedger clear;op={};op.id=1;op.loopID=7;op.clearContinuation=true;clear.accept(op);op.id=2;clear.accept(op);clear.cancelUnstarted(7,7,"Clear",1);clear.cancel(7,7,"Clear cleanup",1);require(!terminal(clear.find(1)->state)&&terminal(clear.find(2)->state));clear.cancel(7,8,"Stop");require(terminal(clear.find(1)->state));
    std::cout<<"{\"expected\":10,\"executed\":10,\"PASS\":true,\"actual_admission_boundary\":4096}"<<std::endl;
}
