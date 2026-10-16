#include "prototype/Phase58Diagnostics.h"
#include "prototype/Phase45PcmDigest.h"
#include <bit>
#include <fstream>
#include <iostream>
#include <sys/resource.h>
using namespace ts::prototype;
int main(int argc,char** argv){try{
    if(argc<8)throw std::invalid_argument("input speed_micros preset reference.f32 frames sha chunk [--worker=workgroup --resident-input=on]");
    phase58::Configuration config;config.speedMicros=std::stoul(argv[2]);const std::string preset=argv[3];
    if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("preset");config.candidate=preset=="candidate";config.analysisChunk=std::stoul(argv[7]);
    for(int i=8;i<argc;++i){const std::string flag=argv[i];
        if(flag=="--worker=workgroup")config.scheduling=phase58::WorkerScheduling::AudioWorkgroup;
        else if(flag=="--worker=standard")config.scheduling=phase58::WorkerScheduling::Standard;
        else if(flag=="--resident-input=on")config.residentInput=true;
        else if(flag=="--resident-input=off")config.residentInput=false;
        else throw std::invalid_argument("Unknown verification option: "+flag);
    }
    phase58::RealtimePipeline engine(argv[1],config);std::ifstream ref(argv[4],std::ios::binary);if(!ref)throw std::runtime_error("Missing independent raw reference");
    std::array<std::vector<float>,2> data;std::array<float*,2> p{};for(std::size_t c=0;c<engine.channels();++c){data[c].resize(4096);p[c]=data[c].data();}
    std::vector<float> packed(4096*engine.channels());Phase45PcmDigest hash;std::size_t frames=0,iteration=0;
    engine.start();const auto waitingBegan=engine.elapsedSeconds();if(!engine.waitUntilReady(std::chrono::seconds(60)))throw std::runtime_error("Prepare failed: "+engine.diagnostics().error);const auto readyReturned=engine.elapsedSeconds();
    const auto initial=engine.diagnostics();const std::array<std::size_t,6> pattern{1,63,127,512,2048,4096};
    const auto limit=std::chrono::steady_clock::now()+std::chrono::minutes(20);
    while(!engine.drained()){
        if(engine.failed())throw std::runtime_error(engine.diagnostics().error);
        if(std::chrono::steady_clock::now()>limit)throw std::runtime_error("Offline drain timeout");
        auto n=pattern[iteration%pattern.size()];const auto available=engine.available();
        if(available<n&&!engine.finished()){std::this_thread::sleep_for(std::chrono::microseconds(200));continue;}
        n=std::min(n,available);if(!n)continue;
        const auto result=engine.pullAudio(p.data(),n);if(result.received!=n)throw std::runtime_error("Offline FIFO discontinuity");
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<engine.channels();++c){
            float expected=0;if(!ref.read(reinterpret_cast<char*>(&expected),sizeof(float)))throw std::runtime_error("Reference exhausted");
            const auto actual=std::bit_cast<std::uint32_t>(p[c][i]),wanted=std::bit_cast<std::uint32_t>(expected);
            if(actual!=wanted){std::cerr<<"Mismatch frame="<<frames+i<<" channel="<<c<<" actual=0x"<<std::hex<<actual<<" expected=0x"<<wanted<<'\n';return 2;}
            packed[i*engine.channels()+c]=p[c][i];}
        hash.update(packed.data(),n*engine.channels()*sizeof(float));frames+=n;++iteration;
    }
    engine.stop();const auto d=engine.diagnostics();const auto sha=hash.finish();
    const bool pass=frames==std::stoull(argv[5])&&sha==argv[6]&&sha==d.pcmSha256&&ref.peek()==EOF&&d.analysisThread&&d.dspThread&&d.analysisThread!=d.dspThread&&!d.missingFrames&&!d.rejectedWrites&&!d.failed&&!d.cancelled&&d.dspDone&&d.analysisDone;
    rusage u{};getrusage(RUSAGE_SELF,&u);
    std::cout<<"{\"PASS\":"<<(pass?"true":"false")<<",\"speed_micros\":"<<config.speedMicros<<",\"preset\":"<<phase58::jsonString(preset)<<",\"chunk\":"<<config.analysisChunk<<",\"early_ready\":"<<(initial.readyS<initial.analysisDoneS||!initial.analysisDone)<<",\"peak_rss_bytes\":"<<u.ru_maxrss;
    std::cout<<",\"ready_wait_s\":"<<readyReturned-waitingBegan<<",\"ready_return_s\":"<<readyReturned<<",\"ready_notification_lag_s\":"<<readyReturned-d.readyS<<",\"wall_s\":"<<engine.elapsedSeconds();
    phase58::writeDiagnostics(std::cout,d);std::cout<<"}\n";return pass?0:2;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
