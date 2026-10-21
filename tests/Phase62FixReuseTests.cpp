#include "prototype/Phase58RealtimePipeline.h"
#include <algorithm>
#include <bit>
#include <cmath>
#include <fstream>
#include <cstring>
#include "audio/WavStream.h"
#include <iostream>
#include <thread>
using namespace ts::prototype::phase58;
static void check(bool v,const char* message){if(!v)throw std::runtime_error(message);}
static void ready(RealtimePipeline& p){p.start();check(p.waitUntilReady(std::chrono::seconds(120)),p.diagnostics().error.c_str());}
template<class P> static void wait(P predicate){const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);while(!predicate()){check(std::chrono::steady_clock::now()<deadline,"supply timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));}}
static void one(const char* path,unsigned speed,bool candidate,std::size_t a,std::size_t b,const char* raw=nullptr,std::size_t expectedA=0,std::size_t expectedB=0){
    Configuration c;c.speedMicros=speed;c.candidate=candidate;c.verifyPcm=false;c.residentInput=true;
    RealtimePipeline base(path,c);ready(base);wait([&]{return base.finalAnalysisAvailable();});
    auto reference=base.createLoopSeek(a,b,speed);auto repeat=base.createLoopSeek(a,b,speed);repeat->enableLoopReuse(a);auto coldContinuation=b<base.inputFrames()?base.createSeek(b,speed):nullptr;base.stop();
    ready(*reference);const auto oa=reference->outputStartFrame(),ob=reference->loopOutputEndFrame(),length=ob-oa,ch=reference->channels();
    std::vector<float> expected(length*ch);std::array<std::array<float,4096>,2> pcm{};float* p[]{pcm[0].data(),pcm[1].data()};std::size_t at=0;
    while(at<length){const auto n=std::min<std::size_t>(4096,length-at);wait([&]{return reference->available()>=n;});auto r=reference->pullAudio(p,n);check(r.received==n&&r.outputBefore==oa+at,"reference coordinates");for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<ch;++j)expected[(at+i)*ch+j]=p[j][i];at+=n;}
    reference->stop();reference.reset();
    if(raw){check(oa==expectedA&&ob==expectedB,"independent TimeMap");std::ifstream f(raw,std::ios::binary);f.seekg(oa*ch*sizeof(float));std::vector<float> oracle(expected.size());f.read(reinterpret_cast<char*>(oracle.data()),oracle.size()*sizeof(float));check(bool(f)&&std::memcmp(expected.data(),oracle.data(),oracle.size()*sizeof(float))==0,"independent RAW");}
    ready(*repeat);check(repeat->loopOutputStartFrame()==oa&&repeat->loopOutputEndFrame()==ob,"reused exact coordinates");at=0;
    const auto total=length*5+127;
    while(at<total){const auto n=std::min<std::size_t>(4096,total-at);wait([&]{check(!repeat->failed(),repeat->diagnostics().error.c_str());return repeat->available()>=n;});auto r=repeat->pullAudio(p,n);check(r.received==n&&r.outputBefore==oa+at%length,"period RAW coordinates");
        for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<ch;++j){const auto actual=p[j][i],want=expected[((at+i)%length)*ch+j];check(std::isfinite(actual)&&std::isfinite(want)&&std::bit_cast<std::uint32_t>(actual)==std::bit_cast<std::uint32_t>(want),"reused RAW bits");}at+=n;
    }
    const auto live=repeat->diagnostics();
    auto continuation=live.loopReuse.cacheBytes&&b<repeat->inputFrames()?repeat->createSeek(b,speed):nullptr;
    repeat->stop();const auto d=repeat->diagnostics();const auto m=d.loopReuse;
    if(continuation){
        ready(*continuation);const auto atB=continuation->outputStartFrame();const auto cursor=continuation->diagnostics();
        check(cursor.reusedInput&&cursor.reusedAnalysis&&cursor.checkpointStartFrame<=atB,"Explicit Exact continuation must reuse input/analysis and start at/before B");
        check(cursor.discardedFrames==atB-cursor.checkpointStartFrame,"Exact continuation cold/checkpoint prefix accounting");
        std::size_t count=0;std::vector<float> suffix;
        if(raw){std::ifstream f(raw,std::ios::binary);f.seekg(0,std::ios::end);const auto size=std::size_t(f.tellg());count=std::min<std::size_t>(4096,size/(ch*sizeof(float))-atB);suffix.resize(count*ch);f.seekg(atB*ch*sizeof(float));f.read(reinterpret_cast<char*>(suffix.data()),suffix.size()*sizeof(float));check(bool(f),"continuation independent oracle");}
        else{ready(*coldContinuation);count=std::min<std::size_t>(4096,coldContinuation->diagnostics().outputFrames-atB);suffix.resize(count*ch);wait([&]{return coldContinuation->available()>=count;});auto r=coldContinuation->pullAudio(p,count);check(r.received==count,"cold B continuation");for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<ch;++c)suffix[i*ch+c]=p[c][i];coldContinuation->stop();}
        wait([&]{return continuation->available()>=count;});const auto r=continuation->pullAudio(p,count);check(r.received==count&&r.outputBefore==atB,"B partial unpublished PCM/cursor");
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<ch;++c)check(std::bit_cast<std::uint32_t>(p[c][i])==std::bit_cast<std::uint32_t>(suffix[i*ch+c]),"B continuation RAW bits");
        continuation->stop();check(continuation->diagnostics().discardedFrames==atB-cursor.checkpointStartFrame,"Exact continuation prefix changed after Ready");
        std::cout<<"B continuation method=ExplicitExact checkpoint="<<cursor.checkpointStartFrame<<" coldDiscard="<<cursor.discardedFrames<<" ReadyS="<<cursor.readyS<<'\n';
    }
    check(d.finalDataAvailable&&!d.failed&&!d.missingFrames,"reuse stop/diagnostics");check(m.mapBuilds==1&&m.workerCreations==2&&m.cyclesPrepared>=5,"map/worker repeated");
    check(m.coldDiscardedFrames==oa,"cold prefix count");check(m.warmDiscardedFrames<=2048*m.seedRestores,"warm prefix depends on A");
    check(m.fftPlanCreations>0&&m.warmFftPlanCreations==0&&m.seedClones==1,"warm FFT plans/seed cloning");
    check(m.cacheBytes?m.cacheReadFrames>0&&m.seedRestores==0:m.seedRestores>=5,"cache/seed reuse");
    std::cout<<"PASS speed="<<speed<<" preset="<<(candidate?"candidate":"baseline")<<" A="<<a<<" B="<<b<<" L="<<length<<" coldDiscard="<<m.coldDiscardedFrames<<" warmDiscard="<<m.warmDiscardedFrames<<" map="<<m.mapBuilds<<" workers="<<m.workerCreations<<" cacheBytes="<<m.cacheBytes<<" restores="<<m.seedRestores<<" fftPlans="<<m.fftPlanCreations<<" warmFftPlans="<<m.warmFftPlanCreations<<" coldPrefixS="<<m.coldPrefixS<<" restoreS="<<m.restoreS<<'\n';
}
int main(int argc,char** argv){try{check(argc==2||argc==9,"input [speed preset A B oracle OA OB]");if(argc==9){one(argv[1],std::stoul(argv[2]),std::string(argv[3])=="candidate",std::stoull(argv[4]),std::stoull(argv[5]),argv[6],std::stoull(argv[7]),std::stoull(argv[8]));return 0;}
    ts::WavStreamReader input(argv[1]);const auto rate=input.sampleRate();
    for(bool candidate:{false,true})for(auto speed:{400000u,2000000u})one(argv[1],speed,candidate,17,rate/10+17);
    one(argv[1],1000000,true,0,input.frames());one(argv[1],400000,false,rate+17,rate*3+17);
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
