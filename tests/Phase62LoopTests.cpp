#include "prototype/Phase58RealtimePipeline.h"
#include "playback/ProgressiveLoopContract.h"
#include "prototype/Phase62LoopBoundary.h"
#include <iostream>
#include <fstream>
#include <cstring>
#include <thread>
#include <cmath>
using ts::prototype::phase58::RealtimePipeline;using ts::prototype::phase58::Configuration;
static void require(bool v,const char* why){if(!v)throw std::runtime_error(why);}
static void ready(RealtimePipeline& p){p.start();require(p.waitUntilReady(std::chrono::seconds(30)),"Ready");}
static std::vector<float> collect(RealtimePipeline& p,std::size_t end){
    std::vector<float> result;std::array<std::array<float,4096>,2> pcm{};float* ptr[]{pcm[0].data(),pcm[1].data()};
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
    while(p.diagnostics().consumed<end){auto position=p.diagnostics().consumed;const auto count=std::min<std::size_t>(4096,end-position);
        if(p.available()<count){require(!p.failed(),"worker failure");require(std::chrono::steady_clock::now()<deadline,"FIFO timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
        auto r=p.pullAudio(ptr,count);require(r.received==count&&r.outputBefore==position,"FIFO sequence");
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<p.channels();++c)result.push_back(ptr[c][i]);
    }return result;
}
int main(int argc,char** argv){try{
    using namespace ts::playback::progressive;using ts::prototype::phase62::Boundary;
    require(validLoopRange(0,1,1)&&!executableLoopRange(0,1,48000),"save/execution split");
    require(!validLoopRange(1,1,2)&&!validLoopRange(0,3,2),"half open");
    for(auto rate:{44100u,48000u})for(unsigned speed=40;speed<=200;++speed){
        const auto length=std::size_t(rate*.5*100/speed);const auto fade=Boundary::fadeLength(rate,length,length);
        require(length>4096+fade,"bounded three spans");Boundary b{length,fade};
        for(auto n:{64u,128u,512u,4096u})for(auto delta:{-1,0,1}){
            const auto position=b.fadeBegin()+delta;const auto expected=delta<0?1u:0u;require(b.prefix(position,n)==expected,"boundary splitting");
        }
    }
    require(argc==2||argc==9,"input [speed preset A B reference.raw startOutput endOutput]");
    Configuration c;c.speedMicros=1000000;c.verifyPcm=false;c.residentInput=true;if(argc==9)c.candidate=std::string(argv[3])=="candidate";
    RealtimePipeline base(argv[1],c);ready(base);
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
    while(!base.finalAnalysisAvailable()){require(std::chrono::steady_clock::now()<deadline,"analysis");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    if(argc==9){
        const auto speed=std::stoul(argv[2]);const bool candidate=std::string(argv[3])=="candidate";
        // A separate source owner is not needed; choose the preset before preparing.
        require(candidate==c.candidate,"preset");
        auto loop=base.createLoopSeek(std::stoull(argv[4]),std::stoull(argv[5]),speed);ready(*loop);
        const auto start=loop->outputStartFrame(),end=loop->loopOutputEndFrame();require(start==std::stoull(argv[7])&&end==std::stoull(argv[8]),"reference A/B");
        auto actual=collect(*loop,end);std::ifstream f(argv[6],std::ios::binary);f.seekg(start*loop->channels()*sizeof(float));std::vector<float> expected(actual.size());f.read(reinterpret_cast<char*>(expected.data()),expected.size()*sizeof(float));
        require(std::all_of(actual.begin(),actual.end(),[](float x){return std::isfinite(x);})&&std::all_of(expected.begin(),expected.end(),[](float x){return std::isfinite(x);}),"nonfinite PCM");
        require(bool(f)&&actual.size()==expected.size()&&std::memcmp(actual.data(),expected.data(),actual.size()*sizeof(float))==0,"independent bounded PCM mismatch");loop->stop();
    }else{
        std::size_t count=0;const auto rate=base.sampleRate();const auto frames=base.inputFrames();
        for(auto speed:{400000u,500000u,750000u,1000000u,1500000u,2000000u})for(auto a:{std::size_t(0),std::min(frames-rate,frames/2+17)}){
            const auto b=std::min(frames,a+rate/2+37);auto loop=base.createLoopSeek(a,b,speed);ready(*loop);
            const auto start=loop->outputStartFrame(),end=loop->loopOutputEndFrame();require(start<end,"mapped range");
            auto actual=collect(*loop,end);loop->stop();require(loop->drained()&&!loop->diagnostics().missingFrames,"bounded EOS");
            require(loop->diagnostics().finalDataAvailable&&loop->diagnostics().sourceHashPasses==1&&loop->diagnostics().residentLockCalls==1,"join/lease");
            auto exact=base.createSeek(a,speed);ready(*exact);require(exact->outputStartFrame()==start,"A mapping");auto expected=collect(*exact,end);exact->stop();require(actual.size()==expected.size()&&std::memcmp(actual.data(),expected.data(),actual.size()*sizeof(float))==0,"exact range PCM bits");++count;
        }
        std::cout<<"bounded exact PCM "<<count<<"/"<<count<<"; 161 speed/rate/callback boundary contracts PASS\n";
    }
    base.stop();
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
