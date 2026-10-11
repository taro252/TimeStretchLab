#include "audio/WavStream.h"
#include "prototype/Phase23VariableSpeedEngine.h"
#include "prototype/Phase30PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>

namespace {
using namespace ts;
using namespace ts::prototype;
using Clock=std::chrono::steady_clock;
void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}
StretchConfig config(const WavStreamReader& input,DecimalSpeed speed) {
    StretchConfig c;
    c.sampleRate=input.sampleRate();c.channels=static_cast<int>(input.channels());
    c.timeRatio=speed.timeRatio();c.enableMultiResolution=true;
    c.qualityMode=QualityMode::Experimental;c.enablePhaseLocking=true;
    c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;
    return c;
}
DecimalSpeed parse(const char* text) {
    std::size_t used=0;
    const std::string value(text);
    const auto number=std::stod(value,&used);
    if (used!=value.size()) throw std::invalid_argument("Invalid speed text");
    return DecimalSpeed::fromDouble(number);
}
struct Change { std::size_t outputFrame; DecimalSpeed target; };
std::vector<Change> schedule(const std::string& path,std::uint32_t rate) {
    std::ifstream file(path);
    if (!file) throw std::runtime_error("Cannot open schedule");
    std::vector<Change> changes;
    std::string line;
    while (std::getline(file,line)) {
        if (line.empty() || line[0]=='#' || line=="output_seconds,target_speed") continue;
        const auto comma=line.find(',');
        if (comma==std::string::npos) throw std::invalid_argument("Invalid schedule row");
        const auto at=static_cast<std::size_t>(std::llround(
            std::stod(line.substr(0,comma))*rate));
        if (!changes.empty() && at<=changes.back().outputFrame)
            throw std::invalid_argument("Schedule must increase");
        changes.push_back({at,parse(line.substr(comma+1).c_str())});
    }
    return changes;
}
}
int main(int argc,char** argv) {
    if (argc==3 && std::string(argv[1])=="--stop") {
        try {
            Phase30PlaybackPipeline pipeline(argv[2],DecimalSpeed::fromDouble(0.50));
            pipeline.start();
            require(pipeline.waitForPrefill(8192,std::chrono::seconds(30)),
                    "Stop test prefill timed out");
            require(pipeline.requestSpeed(DecimalSpeed::fromDouble(0.70),0)==
                    Phase30RequestResult::Accepted,"Stop test request rejected");
            pipeline.stop();
            require(pipeline.finished(),"Stop did not join DSP worker");
            require(pipeline.requestSpeed(DecimalSpeed::fromDouble(0.80),0)==
                    Phase30RequestResult::Stopped,"Post-stop request not rejected");
            std::cout<<"stop_cancelled=1\n";
            return 0;
        } catch (const std::exception& error) {
            std::cerr<<"Phase 30 stop: "<<error.what()<<'\n';
            return 1;
        }
    }
    if (argc==3 && std::string(argv[1])=="--late") {
        try {
            WavStreamReader input(argv[2]);
            Phase30PlaybackPipeline pipeline(argv[2],DecimalSpeed::fromDouble(0.50));
            pipeline.start();
            require(pipeline.waitForPrefill(8192,std::chrono::seconds(30)),
                    "Late test prefill timed out");
            std::vector<std::vector<float>> scratch(input.channels(),
                                                     std::vector<float>(4096));
            std::vector<float*> pointers(input.channels());
            for (std::size_t c=0;c<input.channels();++c)
                pointers[c]=scratch[c].data();
            const auto threshold=pipeline.snapshot().outputLength-20000;
            bool sent=false;
            Phase30RequestResult outcome=Phase30RequestResult::Stopped;
            while (!pipeline.drained()) {
                const auto status=pipeline.snapshot();
                if (!sent && status.presented>=threshold) {
                    outcome=pipeline.requestSpeed(DecimalSpeed::fromDouble(0.70),
                                                  status.presented);
                    require(outcome==Phase30RequestResult::Accepted ||
                            outcome==Phase30RequestResult::Stopped,
                            "Late request had invalid state");
                    sent=true;
                }
                const auto count=std::min<std::size_t>(4096,pipeline.available());
                if (count) require(pipeline.pullAudio(pointers.data(),count)==count,
                                   "Late drain failed");
                else {
                    if (pipeline.finished()) pipeline.rethrowWorkerError();
                    std::this_thread::sleep_for(std::chrono::microseconds(100));
                }
            }
            pipeline.rethrowWorkerError();
            const auto status=pipeline.snapshot();
            require(sent && status.presented==status.outputLength &&
                    !status.underrunFrames && !status.rejectedWrites,
                    "Late request corrupted EOS");
            pipeline.stop();
            std::cout<<"late_request_result="<<static_cast<int>(outcome)<<'\n';
            return 0;
        } catch (const std::exception& error) {
            std::cerr<<"Phase 30 late: "<<error.what()<<'\n';
            return 1;
        }
    }
    if (argc<5 || argc>7) {
        std::cerr<<"Usage: phase30_playback_tests input.wav initial_speed "
                    "target_speed request_output_seconds [capture.wav|-] [golden.wav]\n";
        return 2;
    }
    try {
        const auto input=std::filesystem::path(argv[1]);
        const WavStreamReader reader(input);
        const auto initial=parse(argv[2]);
        const bool scheduled=argv[3][0]=='@';
        const auto target=scheduled ? initial : parse(argv[3]);
        const auto requestSeconds=std::stod(argv[4]);
        auto changes=scheduled ? schedule(argv[3]+1,reader.sampleRate()) :
            std::vector<Change>{};
        if (!scheduled && requestSeconds>=0)
            changes.push_back({static_cast<std::size_t>(
                std::llround(requestSeconds*reader.sampleRate())),target});
        const bool change=!changes.empty();
        const bool capture=argc>=6 && std::string(argv[5])!="-";
        const auto block=std::getenv("PHASE30_TEST_BLOCK") ?
            std::stoull(std::getenv("PHASE30_TEST_BLOCK")) : 2048ULL;
        Phase30PlaybackPipeline pipeline(input,initial,16384,block,12288);
        require(pipeline.requestSpeed(target,0)==Phase30RequestResult::Stopped,
                "Pre-start request not rejected");
        pipeline.start();
        require(pipeline.waitForPrefill(std::min<std::size_t>(8192,
            static_cast<std::size_t>(std::llround(reader.frames()*initial.timeRatio()))),
            std::chrono::seconds(120)),"Prefill timeout");
        require(pipeline.requestSpeed({499999},0)==Phase30RequestResult::Invalid,
                "Invalid speed not rejected");
        require(pipeline.requestSpeed(initial,0)==Phase30RequestResult::Duplicate,
                "Duplicate speed not rejected");
        constexpr std::array<std::size_t,7> blocks={64,128,256,512,1024,2048,4096};
        std::vector<std::vector<float>> output(reader.channels());
        std::vector<std::vector<float>> scratch(reader.channels(),std::vector<float>(4096));
        std::vector<float*> pointers(reader.channels());
        for (std::size_t c=0;c<reader.channels();++c) pointers[c]=scratch[c].data();
        std::size_t frameCount=0,step=0;
        std::size_t requested=0;
        const auto deadline=Clock::now()+std::chrono::minutes(15);
        while (!pipeline.drained()) {
            const auto status=pipeline.snapshot();
            if (requested<changes.size() &&
                status.presented>=changes[requested].outputFrame &&
                (requested==0 || (status.state==Phase30RequestState::Applied &&
                                  status.presented>=status.completionOutput))) {
                require(pipeline.requestSpeed(changes[requested].target,status.presented)==
                    Phase30RequestResult::Accepted,"Speed request rejected");
                require(pipeline.requestSpeed(initial,status.presented)==
                    Phase30RequestResult::Busy,"Overlapping request not rejected");
                ++requested;
            }
            const auto available=pipeline.available();
            if (!available) {
                if (pipeline.finished()) pipeline.rethrowWorkerError();
                require(Clock::now()<deadline,"Drain timeout");
                std::this_thread::sleep_for(std::chrono::microseconds(100));
                continue;
            }
            const auto count=std::min(available,blocks[step++%blocks.size()]);
            require(pipeline.pullAudio(pointers.data(),count)==count,"FIFO shortage");
            if (capture) for (std::size_t c=0;c<reader.channels();++c)
                output[c].insert(output[c].end(),scratch[c].begin(),
                                 scratch[c].begin()+count);
            for (std::size_t c=0;c<reader.channels();++c)
                for (std::size_t i=0;i<count;++i)
                    require(std::isfinite(scratch[c][i]),"Nonfinite DSP output");
            frameCount+=count;
        }
        pipeline.rethrowWorkerError();
        const auto status=pipeline.snapshot();
        const auto plans=pipeline.planMetrics();
        require(frameCount==status.outputLength,"EOS length differs");
        require(status.underrunFrames==0 && status.rejectedWrites==0,
                "FIFO underrun or rejected write");
        require(plans.size()==changes.size(),
                "Request was not planned");
        if (change) {
            require(requested==changes.size() && plans[0].plan.applied(),
                    "Speed plan rejected");
            for (const auto& plan:plans)
                require(plan.plan.applied(),"One of the speed plans was rejected");
            require(plans[0].planningFence>=plans[0].prepared,
                    "Prepared PCM not protected");
            require(plans[0].planningFence>=plans[0].published,
                    "Published PCM not protected");
            require(plans[0].plan.appliedOutputSample>=
                    static_cast<long long>(plans[0].planningFence),
                    "Plan touches protected DSP state");
        }
        if (capture) {
            const auto analysis=Phase13StreamingEngine(config(reader,initial))
                .analyzeTransientEvents(input);
            Phase28ArbitraryTimeMap map(analysis,reader.sampleRate(),initial);
            for (const auto& metric:plans) {
                const auto replay=map.submit({metric.generation,metric.target,
                    metric.requestedInput,static_cast<long long>(metric.planningFence),50.0});
                require(replay.applied(),"Offline TimeMap replay rejected");
                require(replay.appliedOutputSample==metric.plan.appliedOutputSample &&
                        replay.completionOutputSample==metric.plan.completionOutputSample,
                        "Offline TimeMap coordinates differ");
            }
            require(map.monotonic(),"TimeMap not monotonic");
            for (const auto& range:map.measureHops())
                require(range.minimum>0 && !range.nonPositive && !range.outsideWindow,
                        "Synthesis hop unsafe");
            const auto expected=change ? static_cast<std::size_t>(std::llround(
                map.current().outputPositionForInputSample(double(reader.frames())))) :
                static_cast<std::size_t>(std::llround(reader.frames()*initial.timeRatio()));
            require(expected==frameCount,"Offline output length differs");
            std::size_t checked=0;
            const auto referenceResult=Phase23VariableSpeedEngine(config(reader,initial))
                .process(input,analysis,
                map.current(),expected,[&](const float* const* data,std::size_t count) {
                    for (std::size_t c=0;c<reader.channels();++c)
                        require(std::equal(data[c],data[c]+count,
                            output[c].data()+checked),"Realtime PCM differs from offline");
                    checked+=count;
                },8192);
            require(checked==frameCount,"Offline comparison incomplete");
            const auto actualStages=pipeline.stageDigests();
            const auto& expectedStages=referenceResult.stages;
            require(actualStages.fft==expectedStages.fft &&
                    actualStages.phase==expectedStages.phase &&
                    actualStages.ifft==expectedStages.ifft &&
                    actualStages.ola==expectedStages.ola &&
                    actualStages.lowFir==expectedStages.lowFir &&
                    actualStages.highFir==expectedStages.highFir &&
                    actualStages.fir==expectedStages.fir,
                    "FFT/phase/IFFT/OLA/FIR stage digests differ");
            if (change) {
                const auto fixedFrames=static_cast<std::size_t>(std::llround(
                    reader.frames()*initial.timeRatio()));
                std::size_t prefix=0;
                Phase23VariableSpeedEngine(config(reader,initial)).process(input,analysis,
                    *map.fixed(initial),fixedFrames,
                    [&](const float* const* data,std::size_t count) {
                        const auto availablePrefix=prefix<plans[0].published ?
                            std::min(count,plans[0].published-prefix) : 0;
                        if (availablePrefix) for (std::size_t c=0;c<reader.channels();++c)
                            require(std::equal(data[c],data[c]+availablePrefix,
                                output[c].data()+prefix),"Published prefix changed");
                        prefix+=count;
                    },8192);
            }
            WavStreamWriter writer(argv[5],reader.sampleRate(),reader.channels(),frameCount);
            std::vector<const float*> writePointers(reader.channels());
            for (std::size_t c=0;c<reader.channels();++c)
                writePointers[c]=output[c].data();
            writer.write(writePointers.data(),frameCount);writer.finish();
            if (argc==7) {
                WavStreamReader golden(argv[6]);
                require(golden.frames()==frameCount,"Golden frame length differs");
                for (std::size_t c=0;c<reader.channels();++c)
                    for (std::size_t i=0;i<frameCount;++i)
                        require(golden.sample(c,i)==output[c][i],
                                "Fixed speed PCM differs from Golden");
            }
        }
        pipeline.stop();
        require(pipeline.requestSpeed(target,frameCount)==Phase30RequestResult::Stopped,
                "Stopped request not rejected");
        std::cout<<"output_frames="<<frameCount<<'\n'
                 <<"changes="<<plans.size()<<'\n'
                 <<"planning_fence="<<(plans.empty()?0:plans[0].planningFence)<<'\n'
                 <<"applied_output="<<(plans.empty()?0:plans[0].plan.appliedOutputSample)<<'\n'
                 <<"completion_output="<<(plans.empty()?0:plans[0].plan.completionOutputSample)<<'\n'
                 <<"plan_ms="<<(plans.empty()?0:plans[0].planMilliseconds)<<'\n'
                 <<"fifo_high_water="<<status.fifoHighWater<<'\n'
                 <<"underrun_frames="<<status.underrunFrames<<'\n'
                 <<"rejected_writes="<<status.rejectedWrites<<'\n'
                 <<"max_worker_chunk_ms="<<status.maxWorkerChunkSeconds*1000<<'\n'
                 <<"pcm_identical="<<capture<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 30: "<<error.what()<<'\n';
        return 1;
    }
}
