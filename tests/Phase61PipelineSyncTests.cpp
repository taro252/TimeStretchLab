#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase58Diagnostics.h"
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <thread>
#include <sstream>

using namespace ts::prototype::phase58;
using Clock=std::chrono::steady_clock;
void require(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
struct JoinGate {
    std::mutex mutex;std::condition_variable changed;
    bool armed=false,joining=false,timeout=false;unsigned stage=0,permit=0,exits=0;
    static void hook(void* context,LifecycleTestPoint point,std::uint64_t)noexcept{
        auto& x=*static_cast<JoinGate*>(context);std::unique_lock lock(x.mutex);if(!x.armed)return;
        unsigned needed=0;
        switch(point){
            case LifecycleTestPoint::BeforeJoin:x.stage=1;needed=1;break;
            case LifecycleTestPoint::Joining:x.joining=true;break;
            case LifecycleTestPoint::WorkerExit:++x.exits;needed=2;break;
            case LifecycleTestPoint::JoinedBeforeFinalize:x.stage=3;needed=3;break;
            case LifecycleTestPoint::BeforeFinalPublish:x.stage=4;needed=4;break;
        }
        x.changed.notify_all();
        if(needed&&!x.changed.wait_for(lock,std::chrono::seconds(10),[&]{return x.permit>=needed;}))x.timeout=true;
    }
    void wait(unsigned wanted){std::unique_lock lock(mutex);require(changed.wait_for(lock,std::chrono::seconds(10),[&]{return wanted==2?joining&&exits>0:stage>=wanted;}),"lifecycle barrier timeout");}
    void release(unsigned n){std::lock_guard lock(mutex);permit=n;changed.notify_all();}
    ~JoinGate(){release(10);}
};
void incomplete(RealtimePipeline& p,std::uint64_t session,std::size_t& snapshots){
    const auto began=Clock::now();
    for(unsigned i=0;i<128;++i){const auto d=p.diagnostics();
        require(d.session==session&&!d.finalDataAvailable&&d.lifecycle==LifecycleState::Stopping,"premature final diagnostics / session mismatch");
        std::ostringstream json;ts::prototype::phase58::writeDiagnostics(json,d);
        for(const auto* name:{"borrowed_snapshot_owners","transition_map_owners","worker_profile_records","worker_profile_dropped","detail_records","detail_dropped","thread_samples","thread_samples_dropped","thread_sample_errors","dsp_worker_cpu_s","analysis_worker_cpu_s","sampler_cpu_s"})
            require(json.str().find(std::string("\"")+name+"\":null")!=std::string::npos,"unmeasured final JSON fabricated a zero");
        unsigned refused=0;
        try{p.workerRecords();}catch(const std::logic_error&){++refused;}
        try{p.detailEvents();}catch(const std::logic_error&){++refused;}
        try{p.threadSamples();}catch(const std::logic_error&){++refused;}
        try{p.dynamicTimeMap();}catch(const std::logic_error&){++refused;}
        require(refused==4,"export exposed worker/post-join mutable data");++snapshots;
    }
    require(Clock::now()-began<std::chrono::seconds(2),"diagnostics waited for gated join");
}
int main(int argc,char** argv){try{
    require(argc==2||(argc==3&&std::string(argv[2])=="--standard-only"),"input.wav [--standard-only]");std::size_t snapshots=0;
    const bool workgroup=argc==2;
    {
        Configuration c;c.recordWorkerProfile=true;c.detailedDiagnostics=true;c.sampleDspThread=true;
        JoinGate gate;c.lifecycleTestHooks={&gate,JoinGate::hook,0};RealtimePipeline p(argv[1],c);
        require(!p.diagnostics().finalDataAvailable,"unstarted advertised joined data");
        p.start();require(p.waitUntilReady(std::chrono::seconds(20)),"sync Ready");const auto session=p.diagnostics().session;
        {std::lock_guard lock(gate.mutex);gate.armed=true;}
        std::jthread owner([&]{p.stop();});
        // Always release before jthread joins, including failed assertions.
        struct Release {JoinGate& g;~Release(){g.release(10);}} release{gate};
        for(unsigned point:{1u,2u,3u,4u}){gate.wait(point);incomplete(p,session,snapshots);gate.release(point);}
        owner.join();require(!gate.timeout&&gate.exits==3,"worker exit barrier / join timeout");
        const auto d=p.diagnostics();require(d.finalDataAvailable&&d.lifecycle==LifecycleState::Finalized,"final diagnostic missing");
        std::ostringstream finalJson;writeDiagnostics(finalJson,d);require(finalJson.str().find("\"final_data_available\":1")!=std::string::npos&&finalJson.str().find("\"worker_profile_records\":null")==std::string::npos,"final JSON remained unmeasured");
        require(d.workerProfileRecords==p.workerRecords().size()&&d.detailRecords==p.detailEvents().size()&&d.threadSamples==p.threadSamples().size(),"joined exports disagree");
        require(d.workerProfileRecords>0&&d.detailRecords>0,"empty profile test");p.stop();
    }
    for(unsigned fault=0;fault<=3;++fault){Configuration c;c.sampleDspThread=true;c.lifecycleTestHooks.failStartBeforeWorker=fault;
        RealtimePipeline p(argv[1],c);bool caught=false;
        if(fault){try{p.start();}catch(const std::runtime_error&){caught=true;}require(caught,"worker creation fault ignored");}
        p.stop();require(p.diagnostics().finalDataAvailable,"unstarted/partial start not finalized");p.stop();
        bool refused=false;try{p.start();}catch(const std::logic_error&){refused=true;}require(refused,"finalized pipeline restarted");
    }
    // EOS does not authorize final reads; the analysis identity watcher may live.
    {Configuration c;c.residentInput=true;c.dynamicTransitions=workgroup;c.scheduling=workgroup?WorkerScheduling::AudioWorkgroup:WorkerScheduling::Standard;
        RealtimePipeline p(argv[1],c);p.start();require(p.waitUntilReady(std::chrono::seconds(20)),"EOS source Ready");
        auto end=p.createSeek(p.inputFrames(),c.speedMicros);end->start();require(end->waitUntilReady(std::chrono::seconds(20))&&end->finished(),"EOS seek Ready");
        require(!end->diagnostics().finalDataAvailable,"dspDone published final data before stop");
        end->stop();p.stop();require(end->diagnostics().finalDataAvailable&&p.diagnostics().finalDataAvailable,"EOS join missing");if(workgroup)end->dynamicTimeMap();
    }
    // Input failure also requires the owner to join and publish final records.
    {const auto path=std::filesystem::temp_directory_path()/("phase61_sync_"+std::to_string(Clock::now().time_since_epoch().count())+".wav");
        std::filesystem::copy_file(argv[1],path);Configuration c;c.residentInput=true;RealtimePipeline p(path,c);p.start();require(p.waitUntilReady(std::chrono::seconds(20)),"failure source Ready");
        std::filesystem::remove(path);const auto until=Clock::now()+std::chrono::seconds(5);
        while(!p.failed()&&Clock::now()<until)std::this_thread::yield();
        require(p.failed()&&!p.diagnostics().finalDataAvailable,"source failure prematurely finalized");p.stop();
        require(p.diagnostics().finalDataAvailable&&!p.diagnostics().error.empty(),"failed session final reason missing");}
    std::cout<<"PASS "<<snapshots<<" nonblocking snapshots across 4 join barriers; 3 worker exits, unstarted/creation-fault x3/EOS/idempotent stop\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
