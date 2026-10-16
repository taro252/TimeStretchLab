#include "prototype/Phase58RealtimePipeline.h"
#include "audio/WavStream.h"
#include <iostream>
#include <utility>
#include <bit>
#include <fstream>
#include <iterator>
#include <algorithm>
using namespace ts::prototype::phase58;
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Capture {std::vector<float> pcm;std::vector<DetailEvent> events;Diagnostics diagnostics;};
static bool sameBits(const std::vector<float>& a,const std::vector<float>& b){return a.size()==b.size()&&std::equal(a.begin(),a.end(),b.begin(),[](float x,float y){return std::bit_cast<std::uint32_t>(x)==std::bit_cast<std::uint32_t>(y);});}
static Capture capture(const std::filesystem::path& input,Configuration c){
    RealtimePipeline pipeline(input,c);pipeline.start();
    require(pipeline.waitUntilReady(std::chrono::seconds(20)),"Diagnostic pipeline not ready");
    if(c.scheduling==WorkerScheduling::AudioWorkgroup)require(pipeline.setRealtimeRendering(true),"Realtime pipeline not armed");
    Capture result;result.pcm.reserve(4096*pipeline.channels());
    std::array<float,512> left{},right{};float* channels[]{left.data(),right.data()};
    for(unsigned block=0;block<8;++block){
        const auto rendered=pipeline.pullAudio(channels,512);
        require(rendered.received==512,"Prefilled diagnostic prefix missing");
        for(std::size_t i=0;i<512;++i)for(std::size_t ch=0;ch<pipeline.channels();++ch)result.pcm.push_back(channels[ch][i]);
    }
    pipeline.stop();result.events=pipeline.detailEvents();result.diagnostics=pipeline.diagnostics();return result;
}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::invalid_argument("fixture.wav");
    {
        std::ifstream file(argv[1],std::ios::binary);std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
        ts::WavStreamReader disk(argv[1]),memory("/phase58-fix-not-a-file",bytes);
        require(disk.frames()==memory.frames()&&disk.sampleRate()==memory.sampleRate()&&disk.channels()==memory.channels(),"Encoded-memory WAV metadata differs");
        for(const auto sample:{std::size_t(0),disk.frames()/2,disk.frames()-1,std::min(std::size_t(65535),disk.frames()-1),std::min(std::size_t(65536),disk.frames()-1)})
            for(std::size_t channel=0;channel<disk.channels();++channel)require(std::bit_cast<std::uint32_t>(disk.sample(channel,sample))==std::bit_cast<std::uint32_t>(memory.sample(channel,sample)),"Encoded-memory PCM bits differ");
        bytes.resize(12);bool rejected=false;try{ts::WavStreamReader truncated("/phase58-fix-not-a-file",bytes);}catch(const std::runtime_error&){rejected=true;}
        require(rejected,"Truncated memory WAV accepted");
        const std::array<unsigned char,48> nonfinite{'R','I','F','F',40,0,0,0,'W','A','V','E','f','m','t',' ',16,0,0,0,3,0,1,0,0x44,0xac,0,0,0x10,0xb1,2,0,4,0,32,0,'d','a','t','a',4,0,0,0,0,0,0xc0,0x7f};
        ts::WavStreamReader nanSource("/phase58-fix-not-a-file",nonfinite);rejected=false;
        try{nanSource.validateEncodedSamples();}catch(const std::runtime_error&){rejected=true;}
        require(rejected,"Non-finite resident input was not rejected in preparation");
    }
    Configuration off;auto a=capture(argv[1],off);
    require(a.events.empty()&&!a.diagnostics.detailRecords&&!a.diagnostics.detailDropped,"Disabled diagnostics recorded events");
    Configuration on;on.recordWorkerProfile=true;on.detailedDiagnostics=true;auto b=capture(argv[1],on);
    require(sameBits(a.pcm,b.pcm),"Diagnostic observer changed PCM bits");
    require(!b.events.empty()&&!b.diagnostics.detailDropped,"Complete bounded trace missing");
    require(b.diagnostics.detailRecords==b.events.size(),"Detail event count differs");
    require(b.diagnostics.analysisQosQueried&&b.diagnostics.dspQosQueried&&b.diagnostics.analysisQosClass&&b.diagnostics.dspQosClass,"Actual QoS query missing");
    std::vector<std::pair<std::size_t,std::size_t>> stack;double previous=-1;
    for(const auto& e:b.events){
        require(e.atS>=previous,"Detail clock regressed");previous=e.atS;
        const auto key=std::pair{e.stage,e.scope};
        if(e.begin)stack.push_back(key);
        else{require(!stack.empty()&&stack.back()==key,"Unbalanced detail scope");stack.pop_back();}
    }
    require(stack.empty(),"Unclosed detail scope after cancellation");
    Configuration sampled=on;sampled.sampleDspThread=true;auto sampledResult=capture(argv[1],sampled);
    require(sameBits(a.pcm,sampledResult.pcm)&&sampledResult.diagnostics.threadSamples>0&&!sampledResult.diagnostics.threadSampleErrors,"Thread sampling failed or changed PCM");
    Configuration bounded=on;bounded.diagnosticEventLimit=0;auto c=capture(argv[1],bounded);
    require(sameBits(a.pcm,c.pcm)&&c.events.empty()&&c.diagnostics.detailDropped>0,"Diagnostic overflow was hidden or changed PCM");
    Configuration resident=on;resident.residentInput=true;auto residentResult=capture(argv[1],resident);
    require(sameBits(a.pcm,residentResult.pcm)&&residentResult.diagnostics.residentInputBytes>0,"Resident input changed PCM bits");
    Configuration workgroup=resident;workgroup.scheduling=WorkerScheduling::AudioWorkgroup;auto rt=capture(argv[1],workgroup);
    require(sameBits(a.pcm,rt.pcm)&&rt.diagnostics.scheduling.policyMeasured&&rt.diagnostics.scheduling.observedPolicy==2,"Realtime worker changed PCM or lacked realtime policy");
    require(!rt.diagnostics.scheduling.active&&rt.diagnostics.scheduling.joins==rt.diagnostics.scheduling.leaves&&rt.diagnostics.scheduling.restores==rt.diagnostics.scheduling.promotions,"Realtime worker lifetime was not balanced");
    require(rt.diagnostics.borrowedSnapshotOwners<=3&&!rt.diagnostics.failed,"Borrowed snapshot capacity or realtime cancellation failed");
    {Configuration unsafe;unsafe.scheduling=WorkerScheduling::AudioWorkgroup;bool rejected=false;try{RealtimePipeline p(argv[1],unsafe);}catch(const std::invalid_argument&){rejected=true;}require(rejected,"Unprepared realtime input accepted");}
    Configuration invalid;invalid.diagnosticEventLimit=262145;bool rejected=false;
    try{RealtimePipeline pipeline(argv[1],invalid);}catch(const std::invalid_argument&){rejected=true;}
    require(rejected,"Unbounded detail capacity accepted");
    std::cout<<"Phase58 Fix diagnostics PASS\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
