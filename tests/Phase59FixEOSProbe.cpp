#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase58FixAllocationProbe.h"
#include <mach/mach_time.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <thread>

// 診断実行体だけの計数。通常アプリケーションへリンクしない。
void* operator new(std::size_t n){ts::prototype::phase58::noteDspAllocation();if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){ts::prototype::phase58::noteDspAllocation();void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}
void operator delete(void* p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t)noexcept{std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}
using namespace ts::prototype;
namespace {
std::uint64_t nowNs(){static const auto tb=[] {mach_timebase_info_data_t t{};mach_timebase_info(&t);return t;}();return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*tb.numer/tb.denom);}
void require(bool condition,const char* message){if(!condition)throw std::runtime_error(message);}
}
int main(int argc,char** argv){try{
    if(argc!=5&&argc!=7)throw std::invalid_argument("input second_input output paced|unpaced|normal [initial_micros timeout_s]");
    const std::filesystem::path out=argv[3];const std::string mode=argv[4];
    require(mode=="paced"||mode=="unpaced"||mode=="normal","Invalid mode");
    const auto initial=argc==7?std::stoul(argv[5]):2000000;
    const auto timeout=argc==7?std::stoul(argv[6]):30;
    require(initial>=400000&&initial<=2000000&&initial%10000==0&&timeout>0&&timeout<=60,"Invalid bounded parameters");
    require(!std::filesystem::exists(out),"Fresh output required");std::filesystem::create_directories(out);
    std::ofstream events(out/"lifetime.csv");events<<"run,event,mach_ns,published,consumed,fifo,dsp_done,analysis_done,active,session,pipeline_s,bridge_uncertainty_ns\n"<<std::setprecision(17);
    std::ofstream summary(out/"summary.csv");summary<<"run,drained,failed,session,joins,leaves,restores,active,deadline_misses,rt_new,rt_new_measured,max_wall_s,max_cpu_s,pcm_sha256,old_request_rejected,terminal_operations,dsp_thread,sample_dropped,sample_errors\n";
    bool all=true;std::uint64_t previous=0;
    for(unsigned run=0;run<2;++run){
        events<<run<<",construct_request,"<<nowNs()<<",0,0,0,0,0,0,0,-1,0\n";
        phase58::Configuration c;c.speedMicros=initial;c.dynamicTransitions=true;c.residentInput=true;
        c.scheduling=phase58::WorkerScheduling::AudioWorkgroup;c.recordWorkerProfile=true;c.sampleDspThread=true;
        auto p=std::make_unique<phase58::RealtimePipeline>(argv[run?2:1],c);
        const auto mark=[&](const char* event){auto d=p->diagnostics();const auto before=nowNs();const auto seconds=p->elapsedSeconds();const auto after=nowNs();events<<run<<','<<event<<','<<before+(after-before)/2<<','<<d.published<<','<<d.consumed<<','<<p->available()<<','<<d.dspDone<<','<<d.analysisDone<<','<<d.scheduling.active<<','<<d.session<<','<<seconds<<','<<after-before<<'\n';events.flush();};
        mark("constructed");p->start();mark("start_return");
        require(p->waitUntilReady(std::chrono::seconds(10)),"Ready timeout");mark("ready");
        const auto session=p->diagnostics().session;
        const bool stale=!previous||p->requestSpeed(400000,0,previous,previous).result==Phase39RequestResult::Stopped;
        require(p->requestSpeed(1500000,0).result==Phase39RequestResult::Accepted,"Request rejected");
        require(p->setRealtimeRendering(true),"Promotion failed");mark("promoted");
        if(mode=="normal"){
            const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);
            while(p->speedOperations().back().state==phase59::OperationState::Pending||p->speedOperations().back().state==phase59::OperationState::Submitted){
                require(!p->failed()&&std::chrono::steady_clock::now()<until,"Request decision timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            require(p->setRealtimeRendering(false),"Demotion failed");mark("demoted_before_drain");
        }
        std::array<float,512> left{},right{};float* samples[]{left.data(),right.data()};
        auto next=std::chrono::steady_clock::now();const auto end=next+std::chrono::seconds(timeout);
        while(!p->drained()&&!p->failed()&&std::chrono::steady_clock::now()<end){
            if(mode=="paced"){
                next+=std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(512./p->sampleRate()));
                std::this_thread::sleep_until(next);
            }
            if(const auto available=p->available())p->pullAudio(samples,std::min<std::size_t>(512,available));
            else if(mode!="paced")std::this_thread::sleep_for(std::chrono::microseconds(50));
        }
        const bool drained=p->drained();mark(drained?"drained":"drain_timeout_or_failure");
        mark("stop_request");p->stop();mark("stop_return");auto d=p->diagnostics();
        bool terminal=true;for(const auto& op:p->speedOperations())terminal&=op.state!=phase59::OperationState::Pending&&op.state!=phase59::OperationState::Submitted&&op.state!=phase59::OperationState::Applied;
        const bool good=drained&&!d.failed&&d.dspDone&&!d.scheduling.active&&d.scheduling.joins==d.scheduling.leaves&&d.scheduling.leaves==d.scheduling.restores&&stale&&terminal;
        all&=good;
        summary<<std::setprecision(17)<<run<<','<<drained<<','<<d.failed<<','<<session<<','<<d.scheduling.joins<<','<<d.scheduling.leaves<<','<<d.scheduling.restores<<','<<d.scheduling.active<<','<<d.scheduling.deadlineMisses<<','<<d.realtimeNewCalls<<','<<d.realtimeAllocationsMeasured<<','<<d.maxDspWallS<<','<<d.maxDspCpuS<<','<<d.pcmSha256<<','<<stale<<','<<terminal<<','<<d.dspThread<<','<<d.threadSamplesDropped<<','<<d.threadSampleErrors<<'\n';summary.flush();
        std::ofstream workers(out/("worker_"+std::to_string(run)+".csv"));workers<<"output_start,output_end,start_s,published_s,wall_s,cpu_s,realtime,start_ticks,end_ticks,deadline_ticks\n";
        for(const auto& r:p->workerRecords())workers<<std::setprecision(17)<<r.outputStart<<','<<r.outputEnd<<','<<r.startedS<<','<<r.publishedS<<','<<r.wallS<<','<<r.cpuS<<','<<r.realtime<<','<<r.intervalTiming.startTicks<<','<<r.intervalTiming.endTicks<<','<<r.intervalTiming.deadlineTicks<<'\n';
        std::ofstream samplesFile(out/("thread_samples_"+std::to_string(run)+".csv"));samplesFile<<"before_s,after_s,result,state,policy,priority,user_ns,system_ns\n";
        for(const auto& r:p->threadSamples())samplesFile<<std::setprecision(17)<<r.beforeS<<','<<r.afterS<<','<<r.result<<','<<r.state<<','<<r.policy<<','<<r.currentPriority<<','<<r.userNs<<','<<r.systemNs<<'\n';
        p.reset();events<<run<<",destroy_return,"<<nowNs()<<",0,0,0,0,0,0,"<<session<<",-1,0\n";events.flush();
        previous=session;
    }
    std::cout<<(all?"PASS":"FAIL")<<" mode="<<mode<<"\n";return all?0:2;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
