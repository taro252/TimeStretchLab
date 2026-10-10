#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TransientEventMap.h"
#include "prototype/Phase22VariableTimeMap.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void check(bool valid,const char* message) {
    if (!valid) throw std::runtime_error(message);
}
ts::StretchConfig frozen(std::uint32_t sampleRate,std::size_t channels) {
    ts::StretchConfig c;
    c.sampleRate=sampleRate;
    c.channels=static_cast<int>(channels);
    c.timeRatio=2.0;
    c.enableMultiResolution=true;
    c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;
    c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
std::uint64_t hashStarts(const std::vector<long long>& starts) {
    std::uint64_t hash=14695981039346656037ULL;
    for (auto start:starts) {
        hash^=static_cast<std::uint64_t>(start);
        hash*=1099511628211ULL;
    }
    return hash;
}
void fixedRegression(const ts::Phase13TransientAnalysis& analysis,
                     const ts::prototype::VariableTimeMap& prototype) {
    for (double ratio:{2.0,4.0/3.0}) {
        ts::TransientEventMap legacy(analysis.detectorFrames(),
            analysis.activeFrameCount(),1024,ratio);
        std::vector<double> offsets;
        for (const auto& anchor:analysis.anchors()) offsets.push_back(anchor.sampleOffset);
        legacy.refineAnchors(offsets);
        const auto& selected=ratio==2.0
            ? prototype.fixedHalf().starts() : prototype.fixedThreeQuarter().starts();
        check(legacy.starts()==selected,"Fixed map differs from legacy");
        for (std::size_t i=0;i<selected.size();++i)
            check(legacy.resetAt(i)==
                (std::any_of(analysis.events().begin(),analysis.events().end(),
                    [i](const auto& event){return event.peakFrame==i;})),
                  "Fixed reset differs from input event");
    }
}
void scenario(const std::string& source,const ts::Phase13TransientAnalysis& analysis,
              std::uint32_t sampleRate,const std::string& label,
              std::size_t requested,double ms,long long published) {
    ts::prototype::VariableTimeMap prototype(analysis,sampleRate);
    const auto old=prototype.fixedHalf().starts();
    const auto result=prototype.submit({1,requested,published,ms});
    if (!result.applied) {
        check(result.outcome==ts::prototype::PlanOutcome::NoSafeInterval,
              "Unexpected unapplied status");
        check(prototype.current().starts()==old,"Rejected transition changed the fixed map");
        std::cout<<source<<','<<label<<','<<ms<<','<<requested<<','<<published
                 <<",unavailable\n";
        return;
    }
    check(prototype.monotonic(),"Variable map is not increasing");
    check(!prototype.rampTouchesProtectedEvent(result),"Transition overlaps transient");
    const auto& now=prototype.current().starts();
    for (auto i=std::size_t{0};i<=result.appliedFrame;++i)
        check(now[i]==old[i],"Published/pre-switch frame moved");
    for (std::size_t i=0;i<now.size();++i)
        if (old[i]<published) check(now[i]==old[i],"Published output moved");
    // TimeMap also interpolates between Mid frames. Check that a published
    // output coordinate does not move even when the frontier falls inside one.
    for (std::size_t x=0;x<analysis.inputFrames();x+=128) {
        const auto oldPosition=prototype.fixedHalf().outputPositionForInputSample(double(x));
        if (oldPosition<published)
            check(prototype.current().outputPositionForInputSample(double(x))==oldPosition,
                  "Published interpolated position moved");
    }
    if (!result.truncatedByEnd) {
        const auto& target=prototype.fixedThreeQuarter().starts();
        const auto translation=now[result.rampEndFrame]-target[result.rampEndFrame];
        for (auto i=result.rampEndFrame;i<now.size();++i)
            check(now[i]-target[i]==translation,"Post-transition target slope differs");
        for (const auto& anchor:analysis.anchors()) {
            if (!anchor.confident ||
                anchor.absoluteInputSample<result.rampEndFrame*1024) continue;
            const auto difference=prototype.current().outputPositionForInputSample(
                anchor.absoluteInputSample)-
                prototype.fixedThreeQuarter().outputPositionForInputSample(
                    anchor.absoluteInputSample);
            check(std::abs(difference-translation)<1e-8,
                  "Post-transition precise anchor lost its target-map relation");
        }
    }
    for (const auto& anchor:analysis.anchors()) {
        if (!anchor.confident) continue;
        const auto x=anchor.absoluteInputSample;
        if (x<=result.appliedFrame*1024)
            check(prototype.current().outputPositionForInputSample(x)==
                  prototype.fixedHalf().outputPositionForInputSample(x),
                  "Committed precise anchor moved");
    }
    const auto ranges=prototype.measureHops();
    for (const auto& range:ranges)
        check(range.nonPositive==0 && range.outsideWindow==0,
              "Synthesis hop invalid for OLA window");
    const auto actualRampMs=1000.0*(now[result.rampEndFrame]-now[result.appliedFrame])
        /sampleRate;
    const auto priorHop=result.appliedFrame>0
        ? old[result.appliedFrame]-old[result.appliedFrame-1] : 0;
    const auto firstHop=now[result.appliedFrame+1]-now[result.appliedFrame];
    const auto nextHop=result.rampEndFrame+1<now.size()
        ? now[result.rampEndFrame+1]-now[result.rampEndFrame] : 0;
    std::cout<<source<<','<<label<<','<<ms<<','<<requested<<','<<published<<','
             <<result.appliedFrame*1024<<','<<result.appliedOutputSample<<','
             <<result.deferredInputSamples<<','<<result.protectedEventsSkipped<<','
             <<result.truncatedByEnd<<','<<result.rampEndFrame<<','
             <<actualRampMs<<','<<priorHop<<','<<firstHop<<','<<nextHop<<','
             <<ranges[0].minimum<<','<<ranges[0].maximum<<','
             <<ranges[1].minimum<<','<<ranges[1].maximum<<','
             <<ranges[2].minimum<<','<<ranges[2].maximum<<",applied\n";
}
void study(const std::string& name,const ts::Phase13TransientAnalysis& analysis,
           std::uint32_t sampleRate) {
    ts::prototype::VariableTimeMap fixed(analysis,sampleRate);
    fixedRegression(analysis,fixed);
    std::cout<<"fixed,"<<name<<",events="<<analysis.events().size()
             <<",hash050="<<hashStarts(fixed.fixedHalf().starts())
             <<",hash075="<<hashStarts(fixed.fixedThreeQuarter().starts())<<'\n';
    const auto length=analysis.inputFrames();
    const auto middle=(length/2/1024)*1024;
    const auto tail=length>sampleRate/4 ? length-sampleRate/4 : length/2;
    for (double ms:{20.0,50.0,100.0}) {
        scenario(name,analysis,sampleRate,"head",2048,ms,0);
        scenario(name,analysis,sampleRate,"middle",middle,ms,0);
        scenario(name,analysis,sampleRate,"tail",tail,ms,0);
    }
    if (!analysis.events().empty()) {
        const auto& event=analysis.events()[analysis.events().size()/2];
        const auto at=event.peakFrame*1024;
        if (at>1024 && at+1024<length)
            for (const auto [label,position]:{
                     std::pair{"before",at-1024},
                     std::pair{"on",at},
                     std::pair{"after",at+1024}})
                scenario(name,analysis,sampleRate,label,position,50.0,0);
    }
    // 16,384 output frames have already been handed to a future FIFO. The
    // application point must move past this immutable output frontier.
    const auto requested=std::min(length/3,length-2048);
    const auto published=static_cast<long long>(std::llround(
        fixed.fixedHalf().outputPositionForInputSample(double(requested))))+16384;
    scenario(name,analysis,sampleRate,"fifo_ahead",requested,50.0,published);
    // Two requests before either has been published: only the newest survives.
    const auto first=std::min(length/4,length-4096);
    const auto second=first+2048;
    ts::prototype::VariableTimeMap repeated(analysis,sampleRate),latest(analysis,sampleRate);
    repeated.submit({1,first,0,50});
    const auto last=repeated.submit({2,second,0,100});
    const auto single=latest.submit({2,second,0,100});
    check(last.applied && single.applied &&
          repeated.current().starts()==latest.current().starts(),
          "Newest pending request did not supersede old request");
    ts::prototype::VariableTimeMap pending(analysis,sampleRate),fresh(analysis,sampleRate);
    pending.submit({1,first,0,50});
    const auto pendingBefore=pending.current();
    const auto partialFrontier=static_cast<long long>(std::llround(
        pending.fixedHalf().outputPositionForInputSample(double(first-4096))))+137;
    pending.submit({2,second,partialFrontier,100});
    fresh.submit({2,second,partialFrontier,100});
    check(pending.current().starts()==fresh.current().starts(),
          "Pending cancellation changed unpublished coordinates");
    for (std::size_t x=0;x<first;x+=64) {
        const auto at=pendingBefore.outputPositionForInputSample(double(x));
        if (at<partialFrontier)
            check(pending.current().outputPositionForInputSample(double(x))==at,
                  "Pending cancellation moved an interpolated published position");
    }
    try {
        repeated.submit({1,second,0,50});
        throw std::runtime_error("Stale generation accepted");
    } catch (const std::invalid_argument&) {}
    const auto committed=last.appliedOutputSample+
        (repeated.current().starts()[last.appliedFrame+1]-
         repeated.current().starts()[last.appliedFrame])+1;
    const auto beforeAppliedRequest=repeated.current().starts();
    const auto alreadyActive=repeated.submit({3,second+4096,committed,50});
    check(!alreadyActive.applied && repeated.current().starts()==beforeAppliedRequest,
          "Published transition was rolled back");
    check(alreadyActive.outcome==ts::prototype::PlanOutcome::AlreadyActive,
          "Published duplicate request status wrong");
    std::cout<<"repeated,"<<name
             <<",last_generation=2,latest_pending_wins=1,published_transition_immutable=1\n";
}
}
int main(int argc,char** argv) {
    const auto scratch=std::filesystem::temp_directory_path()/
        ("phase22_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(scratch);
    try {
        constexpr std::size_t length=48000*6;
        std::vector<float> left(length),right(length);
        for (std::size_t i=24000;i<length;i+=24000) {
            left[i]=0.8f;
            right[i]=0.8f;
        }
        const float* channels[]={left.data(),right.data()};
        const auto path=scratch/"click.wav";
        {
            ts::WavStreamWriter writer(path,48000,2,length);
            writer.write(channels,length);
            writer.finish();
        }
        const auto config=frozen(48000,2);
        const auto click=ts::Phase13StreamingEngine(config).analyzeTransientEvents(path);
        check(!click.events().empty(),"Click events missing");
        study("click",click,48000);
        if (argc==2) {
            const auto root=std::filesystem::path(argv[1])/"results/phase12/golden/input";
            for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
                const auto source=root/(std::string(name)+".wav");
                ts::WavStreamReader reader(source);
                const auto data=ts::Phase13StreamingEngine(
                    frozen(reader.sampleRate(),reader.channels())).analyzeTransientEvents(source);
                study(name,data,reader.sampleRate());
            }
        }
        std::filesystem::remove_all(scratch);
        return 0;
    } catch (const std::exception& e) {
        std::cerr<<"Phase 22: "<<e.what()<<" (scratch: "<<scratch<<")\n";
        return 1;
    }
}
