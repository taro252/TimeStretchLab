#include "audio/WavStream.h"
#include "prototype/Phase23VariableSpeedEngine.h"
#include "prototype/Phase26PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <sys/resource.h>
#include <thread>

namespace {
using namespace ts;
using namespace ts::prototype;
using Audio=std::array<std::vector<float>,2>;
void require(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
StretchConfig config(std::uint32_t rate,PlaybackSpeed initial) {
    StretchConfig c;
    c.sampleRate=rate;c.channels=2;
    c.timeRatio=initial==PlaybackSpeed::Half ? 2.0 : 4.0/3.0;
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
struct Capture {
    Audio audio;
    Phase26Snapshot status;
    std::vector<BidirectionalPlan> history;
    std::vector<Phase26Snapshot> appliedSnapshots;
};
Capture simulate(const std::filesystem::path& input,PlaybackSpeed initial,
    std::size_t firstAt=0,std::size_t secondAt=0,std::size_t pullBlock=256,
    bool baselineA=false) {
    Phase26PlaybackPipeline pipeline(input,initial,
        baselineA ? 32768 : 16384,baselineA ? 8192 : 2048,
        baselineA ? 32768 : 12288,!baselineA);
    require(pipeline.requestSpeed(initial,0)==Phase26RequestResult::Stopped,
            "Phase 26 request before start was not rejected");
    pipeline.start();
    require(pipeline.waitForPrefill(baselineA ? 16384 : 8192,
                                   std::chrono::seconds(30)),"Phase 26 prefill timeout");
    require(pipeline.requestSpeed(initial,0)==Phase26RequestResult::Duplicate,
            "Phase 26 duplicate initial speed was accepted");
    Audio output;
    Audio scratch={std::vector<float>(pullBlock),std::vector<float>(pullBlock)};
    float* pointers[]={scratch[0].data(),scratch[1].data()};
    bool firstSent=false,secondSent=false;
    std::vector<Phase26Snapshot> snapshots;
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(4);
    while (!pipeline.drained()) {
        const auto state=pipeline.snapshot();
        if (firstAt && !firstSent && state.presented>=firstAt) {
            const auto target=initial==PlaybackSpeed::Half
                ? PlaybackSpeed::ThreeQuarter : PlaybackSpeed::Half;
            require(pipeline.requestSpeed(target,state.presented)==Phase26RequestResult::Accepted,
                    "Phase 26 first request rejected");
            require(pipeline.requestSpeed(initial,state.presented)==Phase26RequestResult::Busy,
                    "Phase 26 overlapping request was accepted");
            firstSent=true;
        }
        if (firstSent && snapshots.empty() && state.state==Phase26RequestState::Applied)
            snapshots.push_back(state);
        if (secondAt && firstSent && !secondSent && state.presented>=secondAt &&
            state.state==Phase26RequestState::Applied &&
            state.presented>=state.completionOutput) {
            require(pipeline.requestSpeed(initial,state.presented)==Phase26RequestResult::Accepted,
                    "Phase 26 second request rejected");
            secondSent=true;
        }
        if (secondSent && snapshots.size()==1 && state.generation==2 &&
            state.state==Phase26RequestState::Applied) snapshots.push_back(state);
        const auto available=pipeline.available();
        if (!available) {
            if (pipeline.finished()) pipeline.rethrowWorkerError();
            require(std::chrono::steady_clock::now()<deadline,"Phase 26 drain timeout");
            std::this_thread::sleep_for(std::chrono::microseconds(100));
            continue;
        }
        const auto count=std::min(pullBlock,available);
        require(pipeline.pullAudio(pointers,count)==count,"Phase 26 FIFO shortage");
        for (std::size_t c=0;c<2;++c)
            output[c].insert(output[c].end(),scratch[c].begin(),scratch[c].begin()+count);
    }
    pipeline.rethrowWorkerError();
    Capture capture{std::move(output),pipeline.snapshot(),pipeline.history(),
                    std::move(snapshots)};
    pipeline.stop();
    require(capture.status.underrunFrames==0 && capture.status.rejectedWrites==0,
            "Phase 26 FIFO error");
    require(capture.audio[0].size()==capture.status.outputLength,
            "Phase 26 final output length differs");
    require(capture.history.size()==(firstAt ? (secondAt ? 2u : 1u) : 0u),
            "Phase 26 command count differs");
    for (const auto& channel:capture.audio)
        for (const auto sample:channel)
            require(std::isfinite(sample),"Phase 26 nonfinite audio");
    return capture;
}
Audio reference(const std::filesystem::path& input,
    const Phase13TransientAnalysis& analysis,const TimeMap& map,
    std::size_t length,PlaybackSpeed initial) {
    Audio output;
    Phase23VariableSpeedEngine(config(WavStreamReader(input).sampleRate(),initial)).process(
        input,analysis,map,length,[&](const float* const* data,std::size_t count) {
            for (std::size_t c=0;c<2;++c)
                output[c].insert(output[c].end(),data[c],data[c]+count);
        },8192);
    return output;
}
void equal(const Audio& a,const Audio& b,const char* message) {
    require(a[0]==b[0] && a[1]==b[1],message);
}
void equalGoldenBytes(const Audio& audio,const std::filesystem::path& input,
                      PlaybackSpeed speed) {
    const auto suffix=speed==PlaybackSpeed::Half ? "_050.wav" : "_075.wav";
    const auto golden=input.parent_path().parent_path()/"raw"/
        (input.stem().string()+suffix);
    if (!std::filesystem::exists(golden)) return;
    const auto temporary=std::filesystem::temp_directory_path()/
        ("phase26_golden_"+input.stem().string()+suffix);
    const float* channels[]={audio[0].data(),audio[1].data()};
    WavStreamWriter writer(temporary,WavStreamReader(input).sampleRate(),2,audio[0].size());
    writer.write(channels,audio[0].size());writer.finish();
    require(std::filesystem::file_size(temporary)==std::filesystem::file_size(golden),
            "Phase 26 Golden byte length differs");
    std::ifstream actual(temporary,std::ios::binary),expected(golden,std::ios::binary);
    std::array<char,65536> a{},b{};
    while (actual && expected) {
        actual.read(a.data(),a.size());expected.read(b.data(),b.size());
        require(actual.gcount()==expected.gcount() &&
                std::equal(a.begin(),a.begin()+actual.gcount(),b.begin()),
                "Phase 26 fixed PCM differs from Golden WAV bytes");
    }
    std::filesystem::remove(temporary);
}
void verify(const std::filesystem::path& input,PlaybackSpeed initial,
    std::size_t firstAt,std::size_t secondAt=0,std::size_t pullBlock=256,
    bool baselineA=false) {
    WavStreamReader reader(input);
    const auto analysis=Phase13StreamingEngine(config(reader.sampleRate(),initial))
        .analyzeTransientEvents(input);
    Phase26BidirectionalTimeMap planned(analysis,reader.sampleRate(),initial);
    const auto initialMap=planned.current();
    const auto capture=simulate(input,initial,firstAt,secondAt,pullBlock,baselineA);
    for (const auto& snap:capture.appliedSnapshots) {
        const auto plan=planned.submit({snap.generation,snap.target,
            snap.requestedInput,static_cast<long long>(snap.planningFence),50.0});
        require(plan.applied(),"Phase 26 offline reference plan rejected");
        require(plan.appliedOutputSample==static_cast<long long>(snap.appliedOutput),
                "Phase 26 offline reference apply coordinate differs");
    }
    const auto expectedLength=firstAt ? static_cast<std::size_t>(std::llround(
        planned.current().outputPositionForInputSample(double(reader.frames())))) :
        static_cast<std::size_t>(std::llround(reader.frames()*
            (initial==PlaybackSpeed::Half ? 2.0 : 4.0/3.0)));
    require(expectedLength==capture.status.outputLength,"Phase 26 EOS length differs");
    equal(capture.audio,reference(input,analysis,planned.current(),expectedLength,initial),
          "Phase 26 live PCM differs from Phase 23 offline reference");
    if (!firstAt) equalGoldenBytes(capture.audio,input,initial);
    if (firstAt) {
        const auto prefix=reference(input,analysis,initialMap,
            static_cast<std::size_t>(std::llround(reader.frames()*
                (initial==PlaybackSpeed::Half ? 2.0 : 4.0/3.0))),initial);
        const auto end=capture.appliedSnapshots[0].preparedAtPlan;
        for (std::size_t c=0;c<2;++c)
            require(std::equal(capture.audio[c].begin(),capture.audio[c].begin()+end,
                               prefix[c].begin()),"Phase 26 prepared PCM changed");
    }
    double peak=0,localStep=0;
    for (const auto& channel:capture.audio) {
        for (const auto sample:channel) peak=std::max(peak,double(std::abs(sample)));
        if (firstAt) {
            const auto at=capture.appliedSnapshots[0].appliedOutput;
            const auto begin=at>256 ? at-256 : 1;
            const auto end=std::min(channel.size(),at+257);
            for (auto i=begin;i<end;++i)
                localStep=std::max(localStep,double(std::abs(channel[i]-channel[i-1])));
        }
    }
    std::cout<<input.filename().string()<<' '
             <<(initial==PlaybackSpeed::Half ? "050" : "075")
             <<" commands="<<capture.history.size()
             <<" length="<<capture.status.outputLength
             <<" peak="<<peak<<" transition_step="<<localStep
             <<" sample-identical";
    for (const auto& plan:capture.history)
        std::cout<<" apply="<<plan.appliedOutputSample
                 <<" complete="<<plan.completionOutputSample;
    std::cout<<'\n';
}
void longDrain(const std::filesystem::path& input) {
    Phase26PlaybackPipeline pipeline(input,PlaybackSpeed::ThreeQuarter);
    pipeline.start();
    require(pipeline.waitForPrefill(8192,std::chrono::seconds(120)),
            "Phase 26 long prefill timeout");
    Audio scratch={std::vector<float>(4096),std::vector<float>(4096)};
    float* data[]={scratch[0].data(),scratch[1].data()};
    constexpr std::array<std::size_t,7> blocks={64,128,256,512,1024,2048,4096};
    std::size_t requested=0,pulled=0,index=0;
    const auto begin=std::chrono::steady_clock::now();
    const auto deadline=begin+std::chrono::minutes(12);
    while (!pipeline.drained()) {
        if (!requested && pulled>=pipeline.sampleRate()*3) {
            require(pipeline.requestSpeed(PlaybackSpeed::Half,pulled)==
                    Phase26RequestResult::Accepted,"Phase 26 long request rejected");
            requested=1;
        }
        const auto available=pipeline.available();
        if (!available) {
            if (pipeline.finished()) pipeline.rethrowWorkerError();
            require(std::chrono::steady_clock::now()<deadline,
                    "Phase 26 long drain timeout");
            std::this_thread::sleep_for(std::chrono::microseconds(100));
            continue;
        }
        const auto count=std::min(available,blocks[index++%blocks.size()]);
        require(pipeline.pullAudio(data,count)==count,"Phase 26 long FIFO shortage");
        for (std::size_t c=0;c<2;++c)
            for (std::size_t i=0;i<count;++i)
                require(std::isfinite(scratch[c][i]),"Phase 26 long nonfinite sample");
        pulled+=count;
    }
    pipeline.rethrowWorkerError();
    const auto status=pipeline.snapshot();
    require(requested && status.state==Phase26RequestState::Applied,
            "Phase 26 long request was not applied");
    require(pulled==status.outputLength && !status.underrunFrames &&
            !status.rejectedWrites,"Phase 26 long EOS/counter mismatch");
    const auto elapsed=std::chrono::duration<double>(
        std::chrono::steady_clock::now()-begin).count();
    rusage usage{};getrusage(RUSAGE_SELF,&usage);
    const auto cpu=usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6+
                   usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6;
    std::cout<<"long_eos input="<<input.filename().string()
             <<" frames="<<pulled<<" seconds="<<elapsed
             <<" cpu_seconds="<<cpu<<" peak_rss_mib="<<usage.ru_maxrss/1048576.0
             <<" max_worker_ms="<<status.maxWorkerChunkSeconds*1000<<'\n';
    pipeline.stop();
}
}
int main(int argc,char** argv) {
    try {
        if (argc==3 && std::string(argv[1])=="--long") {
            longDrain(argv[2]);
        } else if (argc==2) {
            const std::filesystem::path root=argv[1];
            for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
                const auto path=root/"results/phase12/golden/input"/
                    (std::string(name)+".wav");
                WavStreamReader reader(path);
                verify(path,PlaybackSpeed::ThreeQuarter,reader.sampleRate()*2);
                verify(path,PlaybackSpeed::Half,reader.sampleRate()*2);
                verify(path,PlaybackSpeed::ThreeQuarter,0);
                verify(path,PlaybackSpeed::Half,0);
                if (std::string(name)=="mix" || std::string(name)=="drums")
                    verify(path,PlaybackSpeed::Half,reader.sampleRate()*3,
                           reader.sampleRate()*10);
            }
        } else {
            const auto folder=std::filesystem::temp_directory_path()/
                ("phase26_audio_"+std::to_string(
                    std::chrono::steady_clock::now().time_since_epoch().count()));
            std::filesystem::create_directories(folder);
            constexpr std::size_t rate=48000,n=rate*12;
            Audio audio={std::vector<float>(n),std::vector<float>(n)};
            for (std::size_t i=0;i<n;++i) {
                const float tone=0.17f*std::sin(2*3.141592653589793*437.3*i/rate);
                const float click=i%24000==0 ? 0.5f : 0;
                audio[0][i]=tone+click;audio[1][i]=0.8f*tone+click;
            }
            const auto path=folder/"input.wav";
            const float* data[]={audio[0].data(),audio[1].data()};
            WavStreamWriter writer(path,rate,2,n);
            writer.write(data,n);writer.finish();
            verify(path,PlaybackSpeed::Half,0);
            verify(path,PlaybackSpeed::ThreeQuarter,0);
            verify(path,PlaybackSpeed::Half,rate*3);
            verify(path,PlaybackSpeed::ThreeQuarter,rate*3);
            // At a 0.75x start, 2.0 input seconds maps to 2.667 output seconds.
            // Exercise the click itself and both sides of its protection region.
            const auto clickAt=static_cast<std::size_t>(std::llround(rate*8.0/3.0));
            for (const auto offset:{-256,0,256})
                verify(path,PlaybackSpeed::ThreeQuarter,
                       static_cast<std::size_t>(static_cast<long long>(clickAt)+offset));
            verify(path,PlaybackSpeed::Half,rate*3,rate*12,64);
            verify(path,PlaybackSpeed::Half,rate*3,rate*12,4096);
            verify(path,PlaybackSpeed::Half,rate*3,0,256,true);
            std::filesystem::remove_all(folder);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 26 playback: "<<error.what()<<'\n';
        return 1;
    }
}
