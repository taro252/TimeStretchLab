#include "audio/WavStream.h"
#include "prototype/Phase26BidirectionalTimeMap.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
using namespace ts;
using namespace ts::prototype;
void require(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
StretchConfig config(std::uint32_t rate,int channels) {
    StretchConfig c;
    c.sampleRate=rate;c.channels=channels;c.timeRatio=2.0;
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
void valid(const Phase26BidirectionalTimeMap& map,const BidirectionalPlan& plan) {
    require(plan.applied(),"Phase 26 transition not applied");
    require(map.monotonic(),"Non-monotonic Phase 26 TimeMap");
    require(!map.rampTouchesProtectedEvent(plan),"Ramp touches transient protection");
    for (const auto& range:map.measureHops())
        require(range.minimum>0 && !range.nonPositive && !range.outsideWindow,
                "Phase 26 synthesis hop outside OLA window");
}
void run(const std::filesystem::path& input) {
    WavStreamReader reader(input);
    const auto data=Phase13StreamingEngine(config(reader.sampleRate(),
        static_cast<int>(reader.channels()))).analyzeTransientEvents(input);
    VariableTimeMap old(data,reader.sampleRate());
    Phase26BidirectionalTimeMap forward(data,reader.sampleRate(),PlaybackSpeed::Half);
    Phase26BidirectionalTimeMap reverse(data,reader.sampleRate(),PlaybackSpeed::ThreeQuarter);
    require(forward.fixed(PlaybackSpeed::Half).starts()==old.fixedHalf().starts(),
            "Fixed half TimeMap changed");
    require(reverse.fixed(PlaybackSpeed::ThreeQuarter).starts()==old.fixedThreeQuarter().starts(),
            "Fixed three-quarter TimeMap changed");
    const auto n=reader.frames();
    for (const auto initial:{PlaybackSpeed::Half,PlaybackSpeed::ThreeQuarter}) {
        const auto target=initial==PlaybackSpeed::Half
            ? PlaybackSpeed::ThreeQuarter : PlaybackSpeed::Half;
        Phase26BidirectionalTimeMap head(data,reader.sampleRate(),initial);
        const auto headPlan=head.submit({1,target,0,8192,50.0});
        valid(head,headPlan);
        Phase26BidirectionalTimeMap tail(data,reader.sampleRate(),initial);
        const auto nearEnd=n>reader.sampleRate()
            ? n-reader.sampleRate() : n-1;
        const auto fence=static_cast<long long>(std::ceil(
            tail.current().outputPositionForInputSample(double(nearEnd))))+8192;
        const auto tailPlan=tail.submit({1,target,nearEnd,fence,50.0});
        if (tailPlan.applied()) valid(tail,tailPlan);
        else require(tailPlan.outcome==BidirectionalOutcome::NoSafeInterval ||
                     tailPlan.outcome==BidirectionalOutcome::Truncated,
                     "Phase 26 near-EOS command returned unexpected outcome");
    }
    const auto in=n/3;
    const auto halfOutput=static_cast<long long>(std::ceil(
        old.fixedHalf().outputPositionForInputSample(double(in))))+8192;
    const auto oldPlan=old.submit({1,in,halfOutput,50.0});
    require(oldPlan.applied && !oldPlan.truncatedByEnd,"Old A50 not applicable");
    const auto newPlan=forward.submit({1,PlaybackSpeed::ThreeQuarter,in,halfOutput,50.0});
    valid(forward,newPlan);
    require(forward.current().starts()==old.current().starts(),
            "Forward Phase 26 differs from A50");
    const auto threeQuarterOutput=static_cast<long long>(std::ceil(
        reverse.current().outputPositionForInputSample(double(in))))+8192;
    const auto reverseStart=reverse.current().starts();
    const auto backward=reverse.submit({1,PlaybackSpeed::Half,in,
                                        threeQuarterOutput,50.0});
    valid(reverse,backward);
    require(std::equal(reverseStart.begin(),reverseStart.begin()+backward.appliedFrame+1,
                       reverse.current().starts().begin()),
            "Reverse modified protected TimeMap prefix");
    require(reverse.current().starts().back()>reverseStart.back(),
            "Reverse transition failed to increase EOS length");
    const auto reverseHops=reverse.measureHops();
    const auto rejected=reverse.submit({2,PlaybackSpeed::ThreeQuarter,
        backward.appliedFrame*1024,backward.appliedOutputSample+1,50.0});
    require(rejected.outcome==BidirectionalOutcome::TransitionBusy,
            "Transition-in-progress request was not rejected");
    const auto duplicate=reverse.submit({3,PlaybackSpeed::Half,
        backward.rampEndFrame*1024,backward.completionOutputSample,50.0});
    require(duplicate.outcome==BidirectionalOutcome::AlreadyTarget,
            "Duplicate request was not identified");
    const auto stale=reverse.submit({2,PlaybackSpeed::ThreeQuarter,
        backward.rampEndFrame*1024,backward.completionOutputSample,50.0});
    require(stale.outcome==BidirectionalOutcome::Stale,
            "Stale generation was not rejected");
    const auto secondInput=std::max<std::size_t>(n*2/3,
        newPlan.rampEndFrame*1024+2048);
    const auto fence=std::max<long long>(newPlan.rampEndFrame<forward.current().starts().size()
        ? forward.current().starts()[newPlan.rampEndFrame] : 0,
        static_cast<long long>(std::ceil(forward.current().outputPositionForInputSample(
            double(secondInput))))+8192);
    const auto beforeSecond=forward.current().starts();
    const auto second=forward.submit({2,PlaybackSpeed::Half,secondInput,fence,50.0});
    valid(forward,second);
    require(std::equal(beforeSecond.begin(),beforeSecond.begin()+second.appliedFrame+1,
                       forward.current().starts().begin()),
            "Second transition modified prior published TimeMap");
    require(forward.history().size()==2 &&
            forward.history()[0].target==PlaybackSpeed::ThreeQuarter &&
            forward.history()[1].target==PlaybackSpeed::Half,
            "Speed history not retained");
    std::cout<<input.filename().string()<<" forward="<<newPlan.appliedOutputSample
             <<" reverse="<<backward.appliedOutputSample
             <<" two_changes="<<second.appliedOutputSample
             <<" reverse_eos="<<reverse.current().starts().back()
             <<" skipped_events="<<backward.protectedEventsSkipped;
    for (const auto& hops:reverseHops)
        std::cout<<" hop_min_max="<<hops.minimum<<':'<<hops.maximum;
    std::cout<<'\n';
}
}
int main(int argc,char** argv) {
    try {
        if (argc==2) {
            const std::filesystem::path root=argv[1];
            for (const char* name:{"mix","vocal","bass","drums","guitar"})
                run(root/"results/phase12/golden/input"/(std::string(name)+".wav"));
        } else {
            const auto folder=std::filesystem::temp_directory_path()/
                ("phase26_map_"+std::to_string(
                    std::chrono::steady_clock::now().time_since_epoch().count()));
            std::filesystem::create_directories(folder);
            const auto path=folder/"click.wav";
            constexpr std::size_t rate=48000,n=rate*12;
            std::array<std::vector<float>,2> audio={std::vector<float>(n),
                                                    std::vector<float>(n)};
            for (std::size_t i=0;i<n;++i)
                for (auto& channel:audio)
                    channel[i]=0.15f*std::sin(2*3.141592653589793*437.3*i/rate)+
                               (i%24000==0 ? 0.5f : 0.0f);
            const float* samples[]={audio[0].data(),audio[1].data()};
            WavStreamWriter writer(path,rate,2,n);
            writer.write(samples,n);writer.finish();
            run(path);
            std::filesystem::remove_all(folder);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 26 TimeMap: "<<error.what()<<'\n';
        return 1;
    }
}
