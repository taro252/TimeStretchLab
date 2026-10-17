#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase45PcmDigest.h"
#include <bit>
#include <fstream>
#include <iostream>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;
void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
int main(int argc,char** argv){try{
    if(argc!=9&&argc!=12)throw std::invalid_argument("input micros preset input_frame reference expected_start output_frames standard|workgroup [warm_input warm_expected_start checkpoints_on]");
    phase58::Configuration c;c.speedMicros=std::stoul(argv[2]);c.candidate=std::string(argv[3])=="candidate";c.residentInput=true;
    if(std::string(argv[8])=="workgroup"){c.dynamicTransitions=true;c.scheduling=phase58::WorkerScheduling::AudioWorkgroup;}
    if(argc==12)c.seekCheckpoints=std::stoul(argv[11])!=0;
    const auto begin=std::chrono::steady_clock::now();phase58::RealtimePipeline original(argv[1],c);original.start();
    require(original.waitUntilReady(std::chrono::seconds(30)),"original prepare");const auto before=original.diagnostics();
    std::unique_ptr<phase58::RealtimePipeline> warm;
    if(argc==12){warm=original.createSeek(std::stoull(argv[9]),c.speedMicros);warm->start();require(warm->waitUntilReady(std::chrono::seconds(120)),"warm seek Ready");require(warm->outputStartFrame()==std::stoull(argv[10]),"warm map coordinate");original.stop();}
    const auto request=std::chrono::steady_clock::now();auto p=(warm?warm.get():&original)->createSeek(std::stoull(argv[4]),c.speedMicros);p->start();
    require(p->waitUntilReady(std::chrono::seconds(120)),p->diagnostics().error.c_str());
    const auto ready=std::chrono::steady_clock::now();const auto start=p->outputStartFrame();const auto end=std::stoull(argv[7]);
    require(start==std::stoull(argv[6]),"Adaptive map seek coordinate mismatch");
    require(p->inputGeneration()==original.inputGeneration(),"Input lease generation changed");
    require(p->diagnostics().reusedInput&&p->diagnostics().reusedAnalysis&&p->diagnostics().inputSha256==before.inputSha256,"Input/analysis not reused");
    {const auto d=p->diagnostics();require(d.sourceHashPasses==1&&d.sourceSnapshotCreations==1&&d.residentLockCalls==1,"Seek repeated source preparation");}
    original.stop();if(warm)warm->stop();
    if(std::string(argv[8])=="workgroup"){
        require(p->setRealtimeRendering(true),"Seek promotion blocked behind pending PCM");
        const auto m=p->diagnostics().scheduling;
        require(p->finished()||(m.active&&m.policyMeasured&&m.observedPolicy==2),"Seek realtime policy not measured");
    }
    std::ifstream reference(argv[5],std::ios::binary);require(bool(reference),"reference open");reference.seekg(start*p->channels()*sizeof(float));
    std::array<std::array<float,511>,2> pcm{};float* channels[]={pcm[0].data(),pcm[1].data()};std::array<float,1022> packed{};Phase45PcmDigest hash;
    std::size_t at=start;const auto limit=ready+std::chrono::seconds(120);
    while(!p->drained()){
        require(!p->failed(),p->diagnostics().error.c_str());require(std::chrono::steady_clock::now()<limit,"suffix timeout");
        const auto available=p->available();if(!available){std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
        const auto n=std::min(std::size_t(511),available);const auto r=p->pullAudio(channels,n);
        require(r.received==n&&r.outputBefore==at,"FIFO gap/order");
        for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<p->channels();++ch){float expected;require(bool(reference.read(reinterpret_cast<char*>(&expected),4)),"reference exhausted");
            if(std::bit_cast<std::uint32_t>(expected)!=std::bit_cast<std::uint32_t>(pcm[ch][i])){std::cerr<<"PCM mismatch frame="<<at+i<<" channel="<<ch<<'\n';return 2;}packed[i*p->channels()+ch]=pcm[ch][i];}
        hash.update(packed.data(),n*p->channels()*sizeof(float));at+=n;
    }
    p->stop();const auto d=p->diagnostics();const auto digest=hash.finish();
    require(at==end&&reference.peek()==EOF&&d.pcmSha256==digest&&!d.missingFrames&&!d.rejectedWrites,"suffix length/hash/supply");
    require(!d.scheduling.active&&d.scheduling.joins==d.scheduling.leaves&&d.scheduling.leaves==d.scheduling.restores,"workgroup lifetime");
    rusage usage{};getrusage(RUSAGE_SELF,&usage);
    std::cout<<"{\"PASS\":true,\"output_start\":"<<start<<",\"suffix_frames\":"<<at-start<<",\"discarded\":"<<d.discardedFrames<<",\"sha256\":\""<<digest<<"\",\"accepted_to_ready_s\":"<<std::chrono::duration<double>(ready-request).count()<<",\"total_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count()<<",\"peak_rss_bytes\":"<<usage.ru_maxrss<<",\"input_generation\":"<<d.inputGeneration<<",\"source_bytes\":"<<d.sourceSnapshotBytes<<",\"resident_bytes\":"<<d.residentInputBytes<<",\"checkpoint_used\":"<<(d.checkpointUsed?"true":"false")<<",\"checkpoint_start\":"<<d.checkpointStartFrame<<",\"checkpoint_states\":"<<d.checkpointResidentStates<<",\"checkpoint_builds\":"<<d.checkpointBuilds<<",\"realtime_joins\":"<<d.scheduling.joins<<",\"realtime_leaves\":"<<d.scheduling.leaves<<",\"realtime_restores\":"<<d.scheduling.restores<<",\"worker_deadlines\":"<<d.scheduling.deadlineMisses<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
