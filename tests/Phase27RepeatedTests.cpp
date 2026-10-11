#include "audio/WavStream.h"
#include "prototype/Phase23VariableSpeedEngine.h"
#include "prototype/Phase26PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <sys/resource.h>
#include <thread>

namespace {
using namespace ts;
using namespace ts::prototype;
using Audio=std::array<std::vector<float>,2>;
void check(bool okay,const char* message) {
    if (!okay) throw std::runtime_error(message);
}
StretchConfig config(std::uint32_t rate) {
    StretchConfig c;
    c.sampleRate=rate;c.channels=2;c.timeRatio=2.0;
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
std::filesystem::path repeatTo45Seconds(const std::filesystem::path& source,
                                          const std::filesystem::path& folder) {
    WavStreamReader reader(source);
    const auto count=static_cast<std::size_t>(reader.sampleRate())*45;
    const auto path=folder/(source.stem().string()+"_repeated.wav");
    WavStreamWriter writer(path,reader.sampleRate(),2,count);
    Audio block={std::vector<float>(4096),std::vector<float>(4096)};
    std::size_t written=0;
    while (written<count) {
        const auto n=std::min<std::size_t>(4096,count-written);
        for (std::size_t i=0;i<n;++i) for (int c=0;c<2;++c)
            block[c][i]=reader.sample(c,(written+i)%reader.frames());
        const float* data[]={block[0].data(),block[1].data()};
        writer.write(data,n);written+=n;
    }
    writer.finish();return path;
}
void run(const std::filesystem::path& path,int commands,bool comparePcm) {
    WavStreamReader reader(path);
    const auto rate=reader.sampleRate();
    Phase26PlaybackPipeline pipeline(path,PlaybackSpeed::Half);
    pipeline.start();
    check(pipeline.waitForPrefill(8192,std::chrono::seconds(120)),"prefill timeout");
    check(pipeline.requestSpeed(PlaybackSpeed::Half,0)==Phase26RequestResult::Duplicate,
          "duplicate initial request was accepted");
    Audio result,scratch={std::vector<float>(4096),std::vector<float>(4096)};
    float* data[]={scratch[0].data(),scratch[1].data()};
    const std::array<std::size_t,7> blocks={64,128,256,512,1024,2048,4096};
    std::size_t index=0,sent=0,nextAt=rate*2;
    std::uint64_t lastGeneration=0;
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(12);
    while (!pipeline.drained()) {
        auto snap=pipeline.snapshot();
        if (snap.audibleStage==Phase26AudibleStage::Transitioning)
            check(snap.currentAudible==snap.from,
                  "currentAudible moved before transition completed");
        if (snap.audibleStage==Phase26AudibleStage::Complete)
            check(snap.currentAudible==snap.target,
                  "currentAudible did not reach completed target");
        if (sent<static_cast<std::size_t>(commands) && snap.presented>=nextAt &&
            (snap.audibleStage==Phase26AudibleStage::Stable ||
             snap.audibleStage==Phase26AudibleStage::Complete)) {
            const auto current=sent%2==0 ? PlaybackSpeed::Half :
                PlaybackSpeed::ThreeQuarter;
            check(pipeline.requestSpeed(current,snap.presented)==
                  Phase26RequestResult::Duplicate,"completed duplicate not rejected");
            const auto target=sent%2==0 ? PlaybackSpeed::ThreeQuarter : PlaybackSpeed::Half;
            check(pipeline.requestSpeed(target,snap.presented)==Phase26RequestResult::Accepted,
                  "repeated request rejected");
            check(pipeline.requestSpeed(target,snap.presented)==Phase26RequestResult::Busy,
                  "in-flight duplicate not marked busy");
            ++sent;lastGeneration=pipeline.snapshot().generation;
            nextAt+=rate*3/2;
        }
        const auto available=pipeline.available();
        if (!available) {
            if (pipeline.finished()) pipeline.rethrowWorkerError();
            check(std::chrono::steady_clock::now()<deadline,"drain timeout");
            std::this_thread::sleep_for(std::chrono::microseconds(100));
            continue;
        }
        const auto n=std::min(available,blocks[index++%blocks.size()]);
        check(pipeline.pullAudio(data,n)==n,"FIFO underrun");
        if (comparePcm) for (int c=0;c<2;++c)
            result[c].insert(result[c].end(),scratch[c].begin(),scratch[c].begin()+n);
        else for (int c=0;c<2;++c) for (std::size_t i=0;i<n;++i)
            check(std::isfinite(scratch[c][i]),"nonfinite PCM");
    }
    pipeline.rethrowWorkerError();
    const auto snap=pipeline.snapshot();
    const auto metrics=pipeline.planMetrics();
    check(sent==static_cast<std::size_t>(commands) && metrics.size()==sent,
          "not every command applied");
    check(snap.generation==lastGeneration && snap.completedChanges==sent &&
          snap.audibleStage==Phase26AudibleStage::Complete,"final command state mismatch");
    check(!snap.underrunFrames && !snap.rejectedWrites,"FIFO counters nonzero");
    check((!comparePcm || result[0].size()==snap.outputLength),"EOS length mismatch");
    double median=0,worst=0;
    std::vector<double> planTimes;
    for (const auto& metric:metrics) {
        check(metric.plan.applied(),"plan not applied");
        planTimes.push_back(metric.planMilliseconds);
        worst=std::max(worst,metric.planMilliseconds);
    }
    std::sort(planTimes.begin(),planTimes.end());
    median=planTimes[planTimes.size()/2];
    const auto p95=planTimes[static_cast<std::size_t>(std::ceil(
        0.95*planTimes.size()))-1];
    const auto analysis=Phase13StreamingEngine(config(rate)).analyzeTransientEvents(path);
    Phase26BidirectionalTimeMap offline(analysis,rate,PlaybackSpeed::Half);
    for (const auto& metric:metrics) {
            const auto before=offline.current().starts();
            const auto plan=offline.submit({metric.plan.generation,metric.plan.target,
                metric.requestedInput,static_cast<long long>(metric.planningFence),50.0});
            check(plan.applied() && plan.appliedOutputSample==metric.plan.appliedOutputSample,
                  "offline plan differs");
            const auto& after=offline.current().starts();
            check(std::equal(before.begin(),before.begin()+plan.appliedFrame+1,after.begin()),
                  "committed TimeMap prefix changed");
            const auto hops=offline.measureHops();
            for (const auto& hop:hops)
                check(hop.nonPositive==0 && hop.outsideWindow==0,"unsafe synthesis hop");
    }
    check(static_cast<std::size_t>(std::llround(offline.current()
        .outputPositionForInputSample(double(reader.frames()))))==snap.outputLength,
        "final offline output length differs");
    double peak=0,transitionStep=0;
    if (comparePcm) {
        Audio expected;
        Phase23VariableSpeedEngine(config(rate)).process(path,analysis,offline.current(),
            snap.outputLength,[&](const float* const* block,std::size_t n) {
                for (int c=0;c<2;++c)
                    expected[c].insert(expected[c].end(),block[c],block[c]+n);
            },8192);
        check(expected==result,"raw PCM differs from independent offline DSP");
        for (const auto& channel:result) {
            for (const auto sample:channel) {
                check(std::isfinite(sample),"nonfinite PCM");
                peak=std::max(peak,double(std::abs(sample)));
            }
            for (const auto& metric:metrics) {
                const auto at=static_cast<std::size_t>(metric.plan.appliedOutputSample);
                for (auto i=std::max<std::size_t>(1,at>256 ? at-256 : 1);
                     i<std::min(channel.size(),at+257);++i)
                    transitionStep=std::max(transitionStep,
                        double(std::abs(channel[i]-channel[i-1])));
            }
        }
    }
    rusage usage{};getrusage(RUSAGE_SELF,&usage);
    std::cout<<path.filename().string()<<" commands="<<commands
             <<" output_frames="<<snap.outputLength<<" plan_median_ms="<<median
             <<" plan_p95_ms="<<p95
             <<" plan_max_ms="<<worst
             <<" max_worker_ms="<<snap.maxWorkerChunkSeconds*1000
             <<" rss_mib="<<usage.ru_maxrss/1048576.0
             <<" peak="<<peak<<" transition_step="<<transitionStep
             <<" exact_pcm="<<comparePcm<<'\n';
    pipeline.stop();
}
}
int main(int argc,char** argv) {
    try {
        if (argc==2 && std::string(argv[1])=="--synthetic") {
            const auto folder=std::filesystem::temp_directory_path()/"phase27_synthetic";
            std::filesystem::create_directories(folder);
            constexpr std::size_t rate=48000,frames=rate*45;
            const auto path=folder/"click_sine_stereo.wav";
            WavStreamWriter writer(path,rate,2,frames);
            Audio block={std::vector<float>(4096),std::vector<float>(4096)};
            for (std::size_t at=0;at<frames;) {
                const auto n=std::min<std::size_t>(4096,frames-at);
                for (std::size_t i=0;i<n;++i) {
                    const auto time=double(at+i)/rate;
                    const auto click=(at+i)%24000==0 ? 0.6f : 0.0f;
                    block[0][i]=0.17f*std::sin(2*M_PI*437.3*time)+click;
                    block[1][i]=0.14f*std::sin(2*M_PI*437.3*time+0.45)+click;
                }
                const float* data[]={block[0].data(),block[1].data()};
                writer.write(data,n);at+=n;
            }
            writer.finish();
            for (const int count:{2,5,10,30}) run(path,count,true);
            {
                Phase26PlaybackPipeline pipeline(path,PlaybackSpeed::Half);
                pipeline.start();
                check(pipeline.waitForPrefill(8192,std::chrono::seconds(30)),
                      "cancel prefill timeout");
                check(pipeline.requestSpeed(PlaybackSpeed::ThreeQuarter,0)==
                      Phase26RequestResult::Accepted,"cancel request rejected");
                pipeline.stop();
                check(pipeline.snapshot().audibleStage==Phase26AudibleStage::Cancelled,
                      "stop did not cancel pending speed change");
                check(pipeline.requestSpeed(PlaybackSpeed::Half,0)==
                      Phase26RequestResult::Stopped,"request after stop accepted");
            }
            std::filesystem::remove_all(folder);
            return 0;
        }
        if (argc==3) {
            run(argv[1],std::stoi(argv[2]),true);
            return 0;
        }
        if (argc==4 && std::string(argv[1])=="--long") {
            run(argv[2],std::stoi(argv[3]),false);
            return 0;
        }
        if (argc!=2) throw std::runtime_error("usage: phase27_repeated_tests root");
        const std::filesystem::path root=argv[1];
        const auto folder=std::filesystem::temp_directory_path()/"phase27_repeated_sources";
        std::filesystem::create_directories(folder);
        for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
            auto path=root/"results/phase12/golden/input"/(std::string(name)+".wav");
            if (WavStreamReader(path).frames()<48000*40)
                path=repeatTo45Seconds(path,folder);
            for (int count:{2,5,10,30}) run(path,count,true);
        }
        std::filesystem::remove_all(folder);
        return 0;
    } catch (const std::exception& e) {
        std::cerr<<"Phase 27 repeated: "<<e.what()<<'\n';return 1;
    }
}
