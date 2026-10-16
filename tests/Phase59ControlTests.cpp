#include "prototype/Phase58RealtimePipeline.h"
#include <iostream>
#include <thread>
using namespace ts::prototype;
void require(bool v,const char* message){if(!v)throw std::runtime_error(message);}
struct Payload {std::uint64_t version=0;std::array<std::uint64_t,128> values{};};
int main(int argc,char** argv){try{
    phase59::ValueMailbox<Payload> mailbox;std::atomic<bool> done=false;std::atomic<unsigned> errors=0;std::size_t read=0;
    std::thread writer([&]{for(std::uint64_t i=1;i<=200000;++i){Payload p;p.version=i;for(auto& v:p.values)v=i^0xdeadbeef;mailbox.publish(p);}done=true;});
    while(!done.load()){if(auto p=mailbox.read()){for(auto v:p->values)if(v!=(p->version^0xdeadbeef))++errors;++read;}}
    writer.join();require(!errors&&read,"Frontier torn/ABA");
#ifndef PHASE59_MAILBOX_ONLY
    if(argc==2){
        phase58::Configuration c;c.dynamicTransitions=true;c.scheduling=phase58::WorkerScheduling::AudioWorkgroup;c.residentInput=true;
        phase58::RealtimePipeline pipeline(argv[1],c);require(pipeline.requestSpeed(400000,0).result==Phase39RequestResult::Stopped,"Pre-start request accepted");
        pipeline.start();require(pipeline.waitUntilReady(std::chrono::seconds(10)),"Dynamic ready timeout");
        const auto session=pipeline.diagnostics().session;
        require(pipeline.requestSpeed(405000,0).result==Phase39RequestResult::Invalid,"Off-grid speed accepted");
        require(pipeline.requestSpeed(400000,0,session+1,session).result==Phase39RequestResult::Stopped,"Old session accepted");
        require(pipeline.requestSpeed(400000,0,session,session+1).result==Phase39RequestResult::Stopped,"Old input generation accepted");
        for(auto speed:{400000,990000,2000000})require(pipeline.requestSpeed(speed,0,session,session).result==Phase39RequestResult::Accepted,"Valid pending request rejected");
        auto operations=pipeline.speedOperations();require(operations[operations.size()-3].state==phase59::OperationState::Replaced&&operations[operations.size()-2].state==phase59::OperationState::Replaced&&operations.back().state==phase59::OperationState::Pending,"Latest-Wins changed an active request");
        for(std::size_t i=operations.size();i<4096;++i)require(pipeline.requestSpeed(400000+std::uint32_t(i%161)*10000,0).result==Phase39RequestResult::Accepted,"Bounded request admission failed");
        require(pipeline.requestSpeed(400000,0).result==Phase39RequestResult::LimitReached&&pipeline.speedOperations().size()==4096,"Request history grew beyond its bound");
        pipeline.stop();operations=pipeline.speedOperations();require(operations.back().state==phase59::OperationState::Cancelled,"Stop left pending request");
        require(pipeline.requestSpeed(500000,0).result==Phase39RequestResult::Stopped,"Stopped request accepted");
        const auto d=pipeline.diagnostics();require(d.borrowedSnapshotOwners<=3&&d.transitionMapOwners<=3,"Unbounded mailbox owners");
        const auto different=std::filesystem::path(argv[1]).parent_path()/"drums.wav";
        phase58::RealtimePipeline next(different,c);next.start();require(next.waitUntilReady(std::chrono::seconds(10)),"Restart/input switch prepare failed");
        require(next.diagnostics().session!=session,"Session reused");require(next.requestSpeed(400000,0,session,session).result==Phase39RequestResult::Stopped,"Old request mixed into restart");next.stop();
        for(unsigned mutation:{0,1}){
            const auto temporary=std::filesystem::temp_directory_path()/("phase59_input_"+std::to_string(getpid())+"_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
            std::filesystem::create_directory(temporary);const auto input=temporary/"input.wav";std::filesystem::copy_file(argv[1],input);
            phase58::RealtimePipeline p(input,c);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Mutation prepare failed");p.requestSpeed(400000,0);
            if(mutation){const auto replacement=temporary/"replacement.wav";std::filesystem::copy_file(different,replacement);std::filesystem::rename(replacement,input);}else std::filesystem::remove(input);
            const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
            while(!p.failed()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));
            require(p.failed()&&!p.setRealtimeRendering(true),"Deleted/replaced source resumed");require(p.speedOperations().back().state==phase59::OperationState::Cancelled,"Failure left a pending request before stop");p.stop();require(!p.finished()&&p.speedOperations().back().state==phase59::OperationState::Cancelled,"Input failure became EOS/pending");std::filesystem::remove_all(temporary);
        }
        for(unsigned fault:{1,2}){
            auto failing=c;failing.transitionFailureForTest=fault;
            phase58::RealtimePipeline p(argv[1],failing);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Fault prepare failed");require(p.setRealtimeRendering(true),"Fault worker did not arm");
            require(p.requestSpeed(1500000,0).result==Phase39RequestResult::Accepted,"Fault request rejected");
            const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
            while(!p.failed()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));
            p.stop();const auto d=p.diagnostics();require(d.failed&&!d.dspDone&&!d.scheduling.active,"Planner failure became EOS/resumed");
            require(d.scheduling.joins==d.scheduling.leaves&&d.scheduling.leaves==d.scheduling.restores,"Planner failure leaked workgroup");
            require(p.speedOperations().back().state==phase59::OperationState::Cancelled,"Planner failure left request pending");
        }
        for(unsigned attempt:{1,2}){
            auto failing=c;failing.promotionFailureOnAttemptForTest=attempt;phase58::RealtimePipeline p(argv[1],failing);
            p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Promotion fault prepare failed");
            if(attempt==2){require(p.setRealtimeRendering(true),"First promotion failed");require(p.setRealtimeRendering(false),"Pause demotion failed");}
            require(!p.setRealtimeRendering(true),"Injected promotion failure accepted");p.stop();const auto d=p.diagnostics();
            require(d.failed&&!d.dspDone&&!d.scheduling.active&&d.scheduling.joins==d.scheduling.restores,"Promotion failure resumed/leaked workgroup");
        }
        // Exercise EOS -> new Play in one process, including old request IDs.
        // Apply while promoted, then demote with the consumer quiescent. Drain
        // as an offline functional test. Native Release tests own timing gates.
        std::uint64_t previousSession=0;
        for(unsigned run=0;run<2;++run){
            auto lifecycle=c;lifecycle.recordWorkerProfile=true;
            phase58::RealtimePipeline p(run?different:std::filesystem::path(argv[1]),lifecycle);p.start();
            require(p.waitUntilReady(std::chrono::seconds(10)),"EOS restart prepare failed");
            const auto current=p.diagnostics().session;
            if(previousSession)require(p.requestSpeed(400000,0,previousSession,previousSession).result==Phase39RequestResult::Stopped,"Old EOS session request accepted");
            require(p.requestSpeed(1500000,0).result==Phase39RequestResult::Accepted,"EOS transition request rejected");
            require(p.setRealtimeRendering(true),"EOS worker did not arm");
            const auto decisionEnd=std::chrono::steady_clock::now()+std::chrono::seconds(5);
            while(p.speedOperations().back().state==phase59::OperationState::Pending||p.speedOperations().back().state==phase59::OperationState::Submitted){
                require(!p.failed()&&std::chrono::steady_clock::now()<decisionEnd,"EOS request was not decided");
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            require(p.setRealtimeRendering(false),"EOS functional drain did not restore normal policy");
            std::array<float,512> left{},right{};float* samples[]{left.data(),right.data()};
            const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);
            while(!p.drained()&&!p.failed()&&std::chrono::steady_clock::now()<end){
                if(const auto available=p.available())p.pullAudio(samples,std::min<std::size_t>(512,available));
                else std::this_thread::sleep_for(std::chrono::microseconds(50));
            }
            if(!p.drained()||p.failed()){const auto d=p.diagnostics();std::cerr<<"EOS run="<<run<<" generated="<<d.generated<<" published="<<d.published<<" consumed="<<d.consumed<<" output="<<d.outputFrames<<" received="<<d.receivedInput<<" snapshot="<<d.snapshotVersion<<" analysisDone="<<d.analysisDone<<" dspDone="<<d.dspDone<<" failed="<<d.failed<<" error="<<d.error<<" available="<<p.available()<<" attempts="<<d.transitionPlanAttempts<<" stale="<<d.transitionStaleReplans<<" history="<<d.transitionHistory<<" dspCpu="<<d.dspCpuS<<" analysisWait="<<d.analysisWaitS<<" backpressure="<<d.backpressureWaitS<<'\n';p.stop();const auto records=p.workerRecords();for(std::size_t i=records.size()>4?records.size()-4:0;i<records.size();++i){const auto& r=records[i];std::cerr<<"block="<<r.outputEnd<<" snapshot="<<r.snapshotVersion<<" final="<<r.finalSnapshot<<" map="<<r.dynamicMapVersion<<" at="<<r.startedS<<" wall="<<r.wallS<<" cpu="<<r.cpuS<<'\n';}const auto map=p.dynamicTimeMap();std::cerr<<"planner map nodes="<<map.starts().size()<<" end="<<map.starts().back()<<'\n';}
            require(p.drained()&&!p.failed(),"Dynamic EOS did not drain");p.stop();const auto d=p.diagnostics();
            require(d.dspDone&&!d.failed&&!d.scheduling.active&&d.scheduling.joins==d.scheduling.leaves&&d.scheduling.leaves==d.scheduling.restores,"EOS leaked worker lifetime");
            for(const auto& operation:p.speedOperations())require(operation.state!=phase59::OperationState::Pending&&operation.state!=phase59::OperationState::Submitted&&operation.state!=phase59::OperationState::Applied,"EOS left nonterminal request");
            previousSession=current;
        }
        { // A pending request must terminate at EOS before stop() is called.
            auto pendingConfig=c;pendingConfig.speedMicros=2000000;
            phase58::RealtimePipeline p(argv[1],pendingConfig);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Pending EOS prepare failed");
            require(p.requestSpeed(400000,0).result==Phase39RequestResult::Accepted,"Pending EOS request rejected");
            std::array<float,512> left{},right{};float* samples[]{left.data(),right.data()};
            const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);
            while(!p.drained()&&!p.failed()&&std::chrono::steady_clock::now()<end){
                if(const auto available=p.available())p.pullAudio(samples,std::min<std::size_t>(512,available));
                else std::this_thread::sleep_for(std::chrono::microseconds(50));
            }
            require(p.drained()&&!p.failed(),"Pending EOS did not drain");
            const auto settled=std::chrono::steady_clock::now()+std::chrono::seconds(1);
            while(p.speedOperations().back().state==phase59::OperationState::Pending&&std::chrono::steady_clock::now()<settled)std::this_thread::sleep_for(std::chrono::milliseconds(1));
            const auto operation=p.speedOperations().back();require(operation.state==phase59::OperationState::Cancelled&&operation.appliedS<0,"EOS left pending request or applied it after completion");p.stop();
        }
    }
#else
    (void)argc;(void)argv;
#endif
    std::cout<<"PASS frontier_mailbox_reads="<<read<<" Latest-Wins/Invalid/Stale/Stop\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
