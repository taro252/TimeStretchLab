#include "prototype/Phase58RealtimePipeline.h"
#include <fstream>
#include <iostream>
#include <unistd.h>
using namespace ts::prototype::phase58;
static void require(bool b,const char* m){if(!b)throw std::runtime_error(m);}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::invalid_argument("fixture.wav");const std::filesystem::path input=argv[1];
    {Configuration c;c.speedMicros=405000;bool bad=false;try{RealtimePipeline p(input,c);}catch(const std::invalid_argument&){bad=true;}require(bad,"Non-percent speed accepted");}
    {Configuration c;c.sourceSnapshotBytes=1;bool bad=false;try{RealtimePipeline p(input,c);}catch(const std::length_error&){bad=true;}require(bad,"Input snapshot quota not enforced");}
    {Configuration c;c.analysisDelayMs=100;RealtimePipeline p(input,c);p.start();std::array<float,512> l{},r{};float* channels[]{l.data(),r.data()};
        auto got=p.pullAudio(channels,512);require(!got.received&&p.diagnostics().missingFrames==512,"FIFO shortage was hidden");
        p.stop();require(p.diagnostics().cancelled&&!p.diagnostics().dspDone,"Cancel became EOS");}
    {RealtimePipeline p(input);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Not ready");
        std::this_thread::sleep_for(std::chrono::milliseconds(30));require(p.available()<=16384,"FIFO grew");p.stop();require(!p.diagnostics().rejectedWrites,"Backpressure rejected write");}
    {Configuration c;c.candidate=false;RealtimePipeline p(input,c);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Baseline not ready");
        std::this_thread::sleep_for(std::chrono::milliseconds(30));require(p.available()==12288&&p.diagnostics().fifoHighWater==12288,"Baseline stock contract changed");p.stop();}
    auto tmp=std::filesystem::temp_directory_path()/("phase58_source_change_"+std::to_string(getpid())+".wav");std::filesystem::copy_file(input,tmp,std::filesystem::copy_options::overwrite_existing);
    {Configuration c;c.analysisDelayMs=100;RealtimePipeline p(tmp,c);p.start();std::filesystem::resize_file(tmp,100);
        require(!p.waitUntilReady(std::chrono::seconds(3)),"Changed source became ready");p.stop();require(p.failed(),"Input mutation not rejected");}
    std::filesystem::remove(tmp);
    std::filesystem::copy_file(input,tmp,std::filesystem::copy_options::overwrite_existing);
    {RealtimePipeline p(tmp);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Snapshot source not ready");std::filesystem::resize_file(tmp,100);
        const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(!p.failed()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));
        p.stop();require(p.failed(),"Completed-analysis identity monitor missed mutation");}
    std::filesystem::remove(tmp);
    for(unsigned action=0;action<3;++action){
        std::filesystem::copy_file(input,tmp,std::filesystem::copy_options::overwrite_existing);
        {RealtimePipeline p(tmp);p.start();require(p.waitUntilReady(std::chrono::seconds(10)),"Identity case not ready");
            if(action==0)std::filesystem::remove(tmp);
            else if(action==1){std::filesystem::remove(tmp);std::filesystem::copy_file(input,tmp);}
            else std::filesystem::permissions(tmp,std::filesystem::perms::none);
            const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(!p.failed()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));
            p.stop();require(p.failed(),"Deletion/replacement/permission change not rejected");}
        if(std::filesystem::exists(tmp))std::filesystem::remove(tmp);
        {RealtimePipeline recovered(input);recovered.start();require(recovered.waitUntilReady(std::chrono::seconds(10)),"Recovery after input failure failed");recovered.stop();require(!recovered.failed(),"Old failure entered new session");}
    }
    {RealtimePipeline a(input),b(input);a.start();b.start();require(a.waitUntilReady(std::chrono::seconds(10))&&b.waitUntilReady(std::chrono::seconds(10)),"Parallel sessions not ready");
        a.stop();b.stop();require(a.diagnostics().session!=b.diagnostics().session,"Session identity reused");}
    std::cout<<"Phase58 safety PASS\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
