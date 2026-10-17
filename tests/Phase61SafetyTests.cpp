#include "prototype/Phase58RealtimePipeline.h"
#include <iostream>
#include <unistd.h>
using namespace ts::prototype;
void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
int main(int argc,char** argv){try{
    require(argc==2,"input.wav");phase58::Configuration c;c.residentInput=true;c.dynamicTransitions=true;c.scheduling=phase58::WorkerScheduling::AudioWorkgroup;
    phase58::RealtimePipeline first(argv[1],c);first.start();require(first.waitUntilReady(std::chrono::seconds(30)),"first Ready");
    const auto generation=first.inputGeneration();
    for(unsigned percent=40;percent<=200;++percent){auto next=first.createSeek(0,percent*10000);require(next->inputGeneration()==generation,"161 admission changed input generation");}
    bool rejected=false;try{first.createSeek(first.inputFrames()+1,1000000);}catch(const std::out_of_range&){rejected=true;}require(rejected,"Out-of-range frame accepted");
    auto eof=first.createSeek(first.inputFrames(),1000000);eof->start();require(eof->waitUntilReady(std::chrono::seconds(30)),"EOF Ready");
    require(eof->finished()&&eof->drained()&&eof->outputStartFrame()==first.inputFrames(),"EOF seek produced audio");
    auto next=eof->createSeek(50003,750000);next->start();require(next->waitUntilReady(std::chrono::seconds(30)),"Seek after EOF Ready");
    first.stop();eof->stop();
    require(next->setRealtimeRendering(true),"partial seek promotion");
    require(next->diagnostics().scheduling.active,"seek policy inactive");
    require(next->setRealtimeRendering(false),"partial seek demotion while FIFO full");
    auto d=next->diagnostics();require(d.sourceHashPasses==1&&d.sourceSnapshotCreations==1&&d.residentLockCalls==1&&d.inputGeneration==generation,"Source preparation repeated");
    std::array<float,512> left{},right{};float* p[]={left.data(),right.data()};const auto at=next->outputStartFrame();require(next->pullAudio(p,512).outputBefore==at,"Absolute output start lost");next->stop();
    const auto temp=std::filesystem::temp_directory_path()/("phase61_mutation_"+std::to_string(getpid())+".wav");
    std::filesystem::copy_file(argv[1],temp);
    {phase58::RealtimePipeline original(temp,c);original.start();require(original.waitUntilReady(std::chrono::seconds(30)),"mutation Ready");
        auto pending=original.createSeek(original.inputFrames()/2,500000);std::filesystem::remove(temp);pending->start();
        require(!pending->waitUntilReady(std::chrono::seconds(3))&&pending->failed(),"Changed input reused by seek");pending->stop();original.stop();}
    std::filesystem::copy_file(argv[1],temp);
    {phase58::RealtimePipeline original(temp,c);original.start();require(original.waitUntilReady(std::chrono::seconds(30)),"EOF mutation source Ready");
        auto end=original.createSeek(original.inputFrames(),1000000);end->start();require(end->waitUntilReady(std::chrono::seconds(30)),"EOF mutation seek Ready");
        std::filesystem::remove(temp);const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
        while(!end->failed()&&std::chrono::steady_clock::now()<until)std::this_thread::sleep_for(std::chrono::milliseconds(2));
        require(end->failed(),"Empty EOF Ready lost source watcher");end->stop();original.stop();}
    std::filesystem::copy_file(argv[1],temp);
    {phase58::RealtimePipeline original(temp,c);original.start();require(original.waitUntilReady(std::chrono::seconds(30)),"replacement source Ready");
        const auto other=temp.string()+".replacement";std::filesystem::copy_file(argv[1],other);std::filesystem::rename(other,temp);
        bool refused=false;try{original.createSeek(0,500000);}catch(const std::exception&){refused=true;}
        require(refused,"Identical-byte replacement bypassed pinned identity");original.stop();}
    std::filesystem::remove(temp);
    std::cout<<"PASS 161 admissions, EOF, input lease survives old epoch stop, one hash/snapshot/mlock, full-FIFO policy commands, deletion/replacement and EOF source watching\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
