#include "audio/WavStream.h"
#include "prototype/Phase23VariableSpeedEngine.h"
#include "prototype/Phase24PlaybackPipeline.h"
#include "prototype/Phase24StreamingSpeedEngine.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <thread>

namespace {
void require(bool pass,const char* message) {
    if (!pass) throw std::runtime_error(message);
}
ts::StretchConfig config(std::uint32_t rate=48000,double ratio=2.0) {
    ts::StretchConfig c;
    c.sampleRate=rate;c.channels=2;c.timeRatio=ratio;
    c.enableMultiResolution=true;c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
using Audio=std::array<std::vector<float>,2>;
struct Capture { Audio audio;ts::prototype::Phase24Snapshot status; };
Capture simulate(const std::filesystem::path& input,std::size_t block,
                 bool change,std::size_t requestAt,
                 std::size_t fifoFrames=32768,std::size_t dspBlock=8192,
                 std::size_t leadLimit=0,bool pollBlocked=false) {
    ts::prototype::Phase24PlaybackPipeline pipeline(input,fifoFrames,dspBlock,
                                                     leadLimit,pollBlocked);
    pipeline.start();
    require(pipeline.waitForPrefill(leadLimit ? 8192 : 16384,
                                   std::chrono::seconds(30)),"Prefill timeout");
    Audio output;
    std::array<std::vector<float>,2> scratch={std::vector<float>(block),std::vector<float>(block)};
    float* pointers[]={scratch[0].data(),scratch[1].data()};
    bool requested=false;
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(90);
    while (!pipeline.drained()) {
        if (change && !requested && output[0].size()>=requestAt) {
            require(pipeline.requestThreeQuarter(output[0].size()),"Speed request rejected");
            requested=true;
        }
        const auto available=pipeline.available();
        if (!available) {
            if (pipeline.finished()) pipeline.rethrowWorkerError();
            if (std::chrono::steady_clock::now()>deadline) throw std::runtime_error("Drain timeout");
            std::this_thread::sleep_for(std::chrono::microseconds(100));
            continue;
        }
        const auto count=std::min(block,available);
        require(pipeline.pullAudio(pointers,count)==count,"FIFO underrun");
        for (std::size_t c=0;c<2;++c)
            output[c].insert(output[c].end(),scratch[c].begin(),scratch[c].begin()+count);
    }
    pipeline.rethrowWorkerError();
    Capture capture{std::move(output),pipeline.snapshot()};
    pipeline.stop();
    require(capture.status.underrunFrames==0 && capture.status.rejectedWrites==0,
            "FIFO underrun/overflow");
    require(capture.audio[0].size()==capture.status.outputLength,"Output length mismatch");
    if (change) require(capture.status.requestState==ts::prototype::SpeedRequestState::Applied,
                        "Transition not applied");
    return capture;
}
Audio reference(const std::filesystem::path& input,const ts::Phase13TransientAnalysis& analysis,
                const ts::TimeMap& map,std::size_t length,ts::StretchConfig settings=config()) {
    Audio output;
    ts::prototype::Phase23VariableSpeedEngine(settings).process(input,analysis,map,length,
        [&](const float* const* data,std::size_t n) {
            for (std::size_t c=0;c<2;++c)
                output[c].insert(output[c].end(),data[c],data[c]+n);
        },8192);
    return output;
}
Audio phase24Fixed(const std::filesystem::path& input,
    const ts::Phase13TransientAnalysis& analysis,const ts::TimeMap& map,
    std::size_t length,ts::StretchConfig settings,std::size_t chunk=8192) {
    Audio output;
    ts::prototype::Phase24StreamingSpeedEngine(settings).process(input,analysis,map,length,
        [&](const float* const* data,std::size_t n) {
            for (std::size_t c=0;c<2;++c)
                output[c].insert(output[c].end(),data[c],data[c]+n);
        },{},chunk);
    return output;
}
void equal(const Audio& a,const Audio& b,const char* message) {
    require(a[0]==b[0] && a[1]==b[1],message);
}
bool identical(const std::filesystem::path& left,const std::filesystem::path& right) {
    if (std::filesystem::file_size(left)!=std::filesystem::file_size(right)) return false;
    std::ifstream a(left,std::ios::binary),b(right,std::ios::binary);
    return std::equal(std::istreambuf_iterator<char>(a),std::istreambuf_iterator<char>(),
                      std::istreambuf_iterator<char>(b));
}
}
int main(int argc,char** argv) {
    const auto folder=std::filesystem::temp_directory_path()/
        ("phase24_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(folder);
    try {
        constexpr std::size_t n=48000*6;
        Audio inputSamples={std::vector<float>(n),std::vector<float>(n)};
        for (std::size_t i=0;i<n;++i) {
            const float tone=0.15f*std::sin(2*3.141592653589793*437.3*i/48000.0);
            const float click=i%24000==0 ? 0.4f : 0.0f;
            inputSamples[0][i]=tone+click;
            inputSamples[1][i]=0.8f*tone+click;
        }
        const auto input=folder/"input.wav";
        const float* ptr[]={inputSamples[0].data(),inputSamples[1].data()};
        ts::WavStreamWriter writer(input,48000,2,n);
        writer.write(ptr,n);writer.finish();
        const auto analysis=ts::Phase13StreamingEngine(config()).analyzeTransientEvents(input);
        ts::prototype::VariableTimeMap maps(analysis,48000);
        const auto half=reference(input,analysis,maps.fixedHalf(),n*2);
        equal(phase24Fixed(input,analysis,maps.fixedHalf(),n*2,config()),half,
              "Phase 24 fixed 0.50 differs from Phase 23");
        const auto threeQuarter=reference(input,analysis,maps.fixedThreeQuarter(),n*4/3,
                                          config(48000,4.0/3.0));
        equal(phase24Fixed(input,analysis,maps.fixedThreeQuarter(),n*4/3,
                           config(48000,4.0/3.0)),threeQuarter,
              "Phase 24 fixed 0.75 differs from Phase 23");
        equal(phase24Fixed(input,analysis,maps.fixedThreeQuarter(),n*4/3,
                           config(48000,4.0/3.0),2048),threeQuarter,
              "Phase 25 small-block fixed 0.75 differs from Phase 23");
        const auto fixed=simulate(input,256,false,0);
        equal(fixed.audio,half,"Fixed half differs from Phase 23");
        equal(simulate(input,256,false,0,16384,2048,12288,true).audio,half,
              "Phase 25 fixed half differs from Phase 23");
        for (const auto block:{512u,1024u,2048u})
            equal(simulate(input,block,false,0).audio,half,
                  "Fixed output depends on callback block size");
        {
            ts::prototype::Phase24PlaybackPipeline restarted(input);
            restarted.start();
            require(restarted.waitForPrefill(16384,std::chrono::seconds(30)),
                    "First prefill failed");
            restarted.stop();
            restarted.start();
            require(restarted.waitForPrefill(16384,std::chrono::seconds(30)),
                    "Restart prefill failed");
            Audio head={std::vector<float>(1024),std::vector<float>(1024)};
            float* outputPointers[]={head[0].data(),head[1].data()};
            require(restarted.pullAudio(outputPointers,1024)==1024,"Restart underrun");
            for (std::size_t c=0;c<2;++c)
                require(std::equal(head[c].begin(),head[c].end(),half[c].begin()),
                        "Restart PCM differs from fixed reference");
            restarted.stop();
        }
        const auto changed=simulate(input,128,true,48000*3);
        ts::prototype::VariableTimeMap planMap(analysis,48000);
        const auto plan=planMap.submit({1,changed.status.requestedInput,
            static_cast<long long>(changed.status.planningFence),50.0});
        require(plan.applied,"Reference request rejected");
        const auto expectedLength=static_cast<std::size_t>(std::llround(
            planMap.current().outputPositionForInputSample(double(n))));
        require(expectedLength==changed.audio[0].size(),"Reference length mismatch");
        const auto variable=reference(input,analysis,planMap.current(),expectedLength);
        equal(changed.audio,variable,"Live worker differs from Phase 23 variable reference");
        for (const auto tuning: {
                std::array<std::size_t,4>{32768,2048,0,0},
                {16384,8192,12288,0},
                {32768,8192,0,1},
                {16384,8192,12288,1},
                {16384,2048,12288,1}}) {
            const auto trial=simulate(input,256,true,48000*3,
                                      tuning[0],tuning[1],tuning[2],tuning[3]!=0);
            ts::prototype::VariableTimeMap trialMap(analysis,48000);
            const auto trialPlan=trialMap.submit({1,trial.status.requestedInput,
                static_cast<long long>(trial.status.planningFence),50.0});
            require(trialPlan.applied,"Phase 25 plan rejected");
            const auto trialLength=static_cast<std::size_t>(std::llround(
                trialMap.current().outputPositionForInputSample(double(n))));
            equal(trial.audio,reference(input,analysis,trialMap.current(),trialLength),
                  "Phase 25 live PCM differs from Phase 23");
            for (std::size_t c=0;c<2;++c)
                require(std::equal(trial.audio[c].begin(),
                    trial.audio[c].begin()+trial.status.preparedAtPlan,half[c].begin()),
                    "Phase 25 prepared PCM changed");
        }
        for (std::size_t c=0;c<2;++c)
            require(std::equal(changed.audio[c].begin(),
                changed.audio[c].begin()+changed.status.publishedAtRequest,half[c].begin()),
                "Published PCM changed");
        for (const auto [block,requestAt]:{
                std::pair<std::size_t,std::size_t>{64,48000},
                {128,48000*3-256},
                {256,48000*3+256},
                {4096,48000*8}}) {
            const auto boundary=simulate(input,block,true,requestAt);
            ts::prototype::VariableTimeMap referenceMap(analysis,48000);
            const auto p=referenceMap.submit({1,boundary.status.requestedInput,
                static_cast<long long>(boundary.status.planningFence),50.0});
            require(p.applied,"Boundary request not applied");
            const auto length=static_cast<std::size_t>(std::llround(
                referenceMap.current().outputPositionForInputSample(double(n))));
            equal(boundary.audio,reference(input,analysis,referenceMap.current(),length),
                  "Boundary worker differs from Phase 23");
            for (std::size_t c=0;c<2;++c)
                require(std::equal(boundary.audio[c].begin(),
                    boundary.audio[c].begin()+boundary.status.publishedAtRequest,half[c].begin()),
                    "Boundary changed published PCM");
        }
        if (argc==2) {
            const std::filesystem::path root=argv[1];
            for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
                const auto path=root/"results/phase12/golden/input"/(std::string(name)+".wav");
                const ts::WavStreamReader reader(path);
                const auto settings=config(reader.sampleRate());
                const auto data=ts::Phase13StreamingEngine(settings).analyzeTransientEvents(path);
                ts::prototype::VariableTimeMap maps(data,reader.sampleRate());
                for (const auto speed:{0.50,0.75}) {
                    const auto ratio=1.0/speed;
                    const auto length=static_cast<std::size_t>(std::llround(reader.frames()*ratio));
                    const auto golden=root/"results/phase12/golden/raw"/
                        (std::string(name)+(speed==0.50 ? "_050.wav" : "_075.wav"));
                    const auto map=speed==0.50 ? maps.fixedHalf() : maps.fixedThreeQuarter();
                    const auto output=folder/(std::string(name)+(speed==0.50 ? "_050.wav":"_075.wav"));
                    ts::WavStreamWriter goldenWriter(output,reader.sampleRate(),reader.channels(),length);
                    std::size_t index=0;
                    ts::prototype::Phase24StreamingSpeedEngine(config(reader.sampleRate(),ratio))
                        .process(path,data,map,length,[&](const float* const* audio,std::size_t count) {
                            goldenWriter.write(audio,count);
                            index+=count;
                        },{},8192);
                    goldenWriter.finish();
                    require(index==length,"Real Golden length mismatch");
                    require(identical(output,golden),"Phase 24 real Golden bytes differ");
                    const auto smallOutput=folder/(std::string(name)+
                        (speed==0.50 ? "_small_050.wav":"_small_075.wav"));
                    ts::WavStreamWriter smallWriter(smallOutput,reader.sampleRate(),
                                                    reader.channels(),length);
                    ts::prototype::Phase24StreamingSpeedEngine(config(reader.sampleRate(),ratio))
                        .process(path,data,map,length,
                            [&](const float* const* audio,std::size_t count) {
                                smallWriter.write(audio,count);
                            },{},2048);
                    smallWriter.finish();
                    require(identical(smallOutput,golden),
                            "Phase 25 small-block real Golden bytes differ");
                    std::cout<<name<<','<<speed<<",sample-identical\n";
                }
                const auto switched=simulate(path,256,true,reader.frames());
                ts::prototype::VariableTimeMap liveMap(data,reader.sampleRate());
                const auto speedPlan=liveMap.submit({1,switched.status.requestedInput,
                    static_cast<long long>(switched.status.planningFence),50.0});
                require(speedPlan.applied,"Real live speed request was not applied");
                const auto variableLength=static_cast<std::size_t>(std::llround(
                    liveMap.current().outputPositionForInputSample(double(reader.frames()))));
                equal(switched.audio,reference(path,data,liveMap.current(),variableLength,settings),
                      "Real live output differs from Phase 23 variable output");
                auto goldenHalf=ts::WavStreamReader(root/"results/phase12/golden/raw"/
                    (std::string(name)+"_050.wav"));
                for (std::size_t i=0;i<switched.status.publishedAtRequest;++i)
                    for (std::size_t c=0;c<reader.channels();++c)
                        require(switched.audio[c][i]==goldenHalf.sample(c,i),
                                "Real published PCM differs from Golden");
                std::cout<<name<<",switch,sample-identical,request="
                         <<switched.status.requestedOutput<<",published="
                         <<switched.status.publishedAtRequest<<",apply="
                         <<switched.status.appliedOutput<<",complete="
                         <<switched.status.completionOutput<<'\n';
                const auto optimized=simulate(path,256,true,reader.frames(),
                                              16384,2048,12288,true);
                ts::prototype::VariableTimeMap optimizedMap(data,reader.sampleRate());
                const auto optimizedPlan=optimizedMap.submit({1,optimized.status.requestedInput,
                    static_cast<long long>(optimized.status.planningFence),50.0});
                require(optimizedPlan.applied,"Optimized real plan rejected");
                const auto optimizedLength=static_cast<std::size_t>(std::llround(
                    optimizedMap.current().outputPositionForInputSample(double(reader.frames()))));
                equal(optimized.audio,reference(path,data,optimizedMap.current(),
                      optimizedLength,settings),"Optimized real output differs from Phase 23");
                for (std::size_t i=0;i<optimized.status.preparedAtPlan;++i)
                    for (std::size_t c=0;c<reader.channels();++c)
                        require(optimized.audio[c][i]==goldenHalf.sample(c,i),
                                "Optimized prepared PCM differs from Golden");
                std::cout<<name<<",phase25,sample-identical,request="
                         <<optimized.status.requestedOutput<<",prepared="
                         <<optimized.status.preparedAtPlan<<",apply="
                         <<optimized.status.appliedOutput<<'\n';
                if (std::string(name)=="mix" || std::string(name)=="drums") {
                    std::size_t eventInput=0;
                    for (const auto& event:data.events()) {
                        const auto at=event.peakFrame*1024;
                        if (at>reader.frames()/3 && at<reader.frames()*2/3) {
                            eventInput=at;
                            break;
                        }
                    }
                    require(eventInput!=0,"No middle transient for Phase 25 test");
                    const auto eventOutput=static_cast<std::size_t>(std::llround(
                        maps.fixedHalf().outputPositionForInputSample(double(eventInput))));
                    for (const auto requestAt:{eventOutput-256,eventOutput,eventOutput+256,
                                              reader.frames()*3/2}) {
                        const auto trial=simulate(path,256,true,requestAt,
                                                  16384,2048,12288,true);
                        ts::prototype::VariableTimeMap candidateMap(data,reader.sampleRate());
                        const auto candidate=candidateMap.submit({1,trial.status.requestedInput,
                            static_cast<long long>(trial.status.planningFence),50.0});
                        require(candidate.applied,"Phase 25 event/late plan rejected");
                        const auto candidateLength=static_cast<std::size_t>(std::llround(
                            candidateMap.current().outputPositionForInputSample(
                                double(reader.frames()))));
                        equal(trial.audio,reference(path,data,candidateMap.current(),
                            candidateLength,settings),"Phase 25 event/late PCM differs");
                        for (std::size_t i=0;i<trial.status.preparedAtPlan;++i)
                            for (std::size_t c=0;c<reader.channels();++c)
                                require(trial.audio[c][i]==goldenHalf.sample(c,i),
                                        "Phase 25 event/late prepared PCM changed");
                    }
                }
            }
        }
        std::cout<<"phase24 fixed and variable sample exact; request="
                 <<changed.status.requestedOutput<<" published="
                 <<changed.status.publishedAtRequest<<" apply="
                 <<changed.status.appliedOutput<<" complete="
                 <<changed.status.completionOutput<<"\n";
        std::filesystem::remove_all(folder);
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<" ("<<folder<<")\n";
        return 1;
    }
}
