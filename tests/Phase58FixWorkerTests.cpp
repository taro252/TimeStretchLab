#include "prototype/Phase58FixRealtimeWorker.h"
#include <thread>
#include <iostream>
#include <cmath>
#include <exception>
#include <stdexcept>
using namespace ts::prototype::phase58;
int main(){try{
    RealtimeWorkerSupport disabled(false,0);disabled.signal();disabled.waitForSignal();
    if(disabled.active()||disabled.metrics().waitCalls)throw std::runtime_error("Disabled realtime support ran");
    bool rejected=false;try{RealtimeWorkerSupport invalid(true,1);}catch(const std::invalid_argument&){rejected=true;}
    if(!rejected)throw std::runtime_error("Unsupported realtime rate accepted");
    RealtimeWorkerSupport worker(true,48000);for(unsigned i=0;i<1000;++i)worker.signal();
    std::exception_ptr error;
    std::thread thread([&]{try{
        for(unsigned epoch=0;epoch<2;++epoch){
            if(!worker.promote()||!worker.promote())throw std::runtime_error("Realtime promotion failed");
            for(unsigned i=0;i<8;++i){
                if(!worker.beginInterval())throw std::runtime_error("Realtime interval start failed");
                volatile double value=.1;for(unsigned j=0;j<128;++j)value=std::sin(value+.001);
                if(!worker.finishInterval())throw std::runtime_error("Realtime interval finish failed");
                worker.waitForSignal();
            }
            if(!worker.demote())throw std::runtime_error("Normal-policy restoration failed");
        }
    }catch(...){worker.demote();error=std::current_exception();}});thread.join();if(error)std::rethrow_exception(error);
    const auto m=worker.metrics();
    if(!m.policyMeasured||m.observedPolicy!=2||m.observedPriority<64||m.restoredPolicy!=1||m.active||m.promotions!=2||m.joins!=2||m.leaves!=2||m.restores!=2||m.intervalStarts!=16||m.intervalFinishes!=16||m.policyErrors||m.joinErrors||m.restoreErrors||m.intervalErrors||m.queryErrors||m.waitErrors||m.wakeErrors)throw std::runtime_error("Realtime lifecycle or diagnostics differ");
    std::cout<<"Phase58 Fix realtime lifecycle PASS\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
