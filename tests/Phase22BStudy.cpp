#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "prototype/Phase22BResponsiveMap.h"
#include "prototype/Phase22VariableTimeMap.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using ts::prototype::VariableTimeMap;
void check(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
ts::StretchConfig frozen(std::uint32_t rate,std::size_t channels) {
    ts::StretchConfig config;
    config.sampleRate=rate;
    config.channels=static_cast<int>(channels);
    config.timeRatio=2.0;
    config.enableMultiResolution=true;
    config.qualityMode=ts::QualityMode::Experimental;
    config.enablePhaseLocking=true;
    config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true;
    config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true;
    return config;
}
std::uint64_t digest(const std::vector<long long>& starts) {
    std::uint64_t hash=14695981039346656037ULL;
    for (const auto start:starts) {
        hash^=static_cast<std::uint64_t>(start);
        hash*=1099511628211ULL;
    }
    return hash;
}
struct Result {
    std::string status="unapplied";
    ts::TimeMap map;
    std::size_t firstChange=0,completion=0,paused=0;
    long long scheduledOutput=0;
    bool changed=false,complete=false;
};
std::size_t firstChangedInterval(const ts::TimeMap& old,const ts::TimeMap& candidate) {
    const auto& a=old.starts();
    const auto& b=candidate.starts();
    for (std::size_t i=0;i+1<a.size();++i)
        if (b[i+1]-b[i]!=a[i+1]-a[i]) return i;
    return a.size();
}
Result run(const std::string& variant,
    const ts::Phase13TransientAnalysis& analysis,std::uint32_t rate,
    std::size_t requested,long long published) {
    VariableTimeMap prototype(analysis,rate);
    const auto half=prototype.fixedHalf(),target=prototype.fixedThreeQuarter();
    Result result;
    result.map=half;
    if (variant=="C100") {
        const auto paused=ts::prototype::buildPausedTransition(
            analysis,half,target,rate,requested,published,100);
        result.map=paused.map;
        result.paused=paused.pausedIntervals;
        result.changed=paused.outcome!=ts::prototype::PausedTransition::Outcome::Unapplied;
        result.complete=paused.outcome==ts::prototype::PausedTransition::Outcome::Completed;
        result.status=result.complete ? "complete" : result.changed ? "partial" : "unapplied";
        result.firstChange=paused.firstChangedFrame;
        result.completion=paused.completionFrame;
        result.scheduledOutput=result.changed
            ? result.map.starts()[paused.firstChangedFrame] : 0;
        check(paused.protectedIntervalsChanged==0,"C changed protected interval");
        return result;
    }
    const double transition=variant=="A20" ? 20
        : variant=="B100" ? 100 : 50;
    const auto plan=prototype.submit({1,requested,published,transition});
    if (!plan.applied) return result;
    result.map=prototype.current();
    result.scheduledOutput=plan.appliedOutputSample;
    result.firstChange=firstChangedInterval(half,result.map);
    if (result.firstChange>=result.map.starts().size()-1) return result;
    result.changed=true;
    result.complete=!plan.truncatedByEnd;
    result.completion=plan.rampEndFrame;
    result.status=result.complete ? "complete" : "partial";
    if (variant=="D250" || variant=="D500" || variant=="D1000") {
        const auto requestOutput=std::llround(half.outputPositionForInputSample(double(requested)));
        const auto elapsed=result.map.starts()[result.firstChange]-requestOutput;
        const double deadlineMs=variant=="D250" ? 250.0
            : variant=="D500" ? 500.0 : 1000.0;
        if (elapsed>std::llround(deadlineMs*rate/1000.0)) {
            result=Result{};
            result.status="expired";
            result.map=half;
        }
    }
    return result;
}
struct Ranges {
    std::array<long long,3> minimum{},maximum{};
    std::array<std::size_t,3> invalid{};
};
Ranges measure(const ts::TimeMap& map) {
    constexpr std::array<int,3> inputHop{2048,1024,256};
    constexpr std::array<int,3> window{8192,4096,1024};
    Ranges value;
    for (auto& x:value.minimum) x=std::numeric_limits<long long>::max();
    const auto last=(map.starts().size()-2)*1024;
    for (std::size_t r=0;r<3;++r) {
        long long prior=0;
        bool first=true;
        for (std::size_t input=0;input<=last;input+=inputHop[r]) {
            const auto position=std::llround(map.outputPositionForInputSample(double(input)));
            if (!first) {
                const auto hop=position-prior;
                value.minimum[r]=std::min(value.minimum[r],hop);
                value.maximum[r]=std::max(value.maximum[r],hop);
                if (hop<=0 || hop>=window[r]) ++value.invalid[r];
            }
            first=false;
            prior=position;
        }
    }
    return value;
}
std::size_t eventDisturbances(const ts::Phase13TransientAnalysis& analysis,
    const ts::TimeMap& map,const ts::TimeMap& half,const ts::TimeMap& target) {
    const auto& current=map.starts();
    std::vector<bool> protectedFrame(current.size());
    for (const auto& event:analysis.events()) {
        const auto first=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto last=std::min(current.size()-1,std::max(event.endFrame,event.peakFrame)+5);
        bool oldSeen=false,targetSeen=false;
        for (auto i=first;i<last;++i) {
            const auto hop=current[i+1]-current[i];
            const auto oldHop=half.starts()[i+1]-half.starts()[i];
            const auto targetHop=target.starts()[i+1]-target.starts()[i];
            if (oldHop==targetHop) continue;
            oldSeen|=hop==oldHop;
            targetSeen|=hop==targetHop;
        }
        check(!(oldSeen && targetSeen),"Speed mode changed inside protected event");
        for (auto i=first;i<=last;++i) protectedFrame[i]=true;
    }
    std::size_t violations=0;
    for (std::size_t i=0;i+1<current.size();++i) {
        if (!protectedFrame[i] && !protectedFrame[i+1]) continue;
        const auto hop=current[i+1]-current[i];
        const auto oldHop=half.starts()[i+1]-half.starts()[i];
        const auto targetHop=target.starts()[i+1]-target.starts()[i];
        if (hop!=oldHop && hop!=targetHop) ++violations;
    }
    return violations;
}
void scenario(const std::string& name,const ts::Phase13TransientAnalysis& analysis,
    std::uint32_t rate,const std::string& position,std::size_t requested,
    std::size_t fifoAhead) {
    VariableTimeMap reference(analysis,rate);
    const auto& half=reference.fixedHalf();
    const auto requestOutput=std::llround(half.outputPositionForInputSample(double(requested)));
    const auto published=fifoAhead ? requestOutput+static_cast<long long>(fifoAhead) : 0;
    for (const char* variant:{"A20","A50","B100","C100",
                             "D250","D500","D1000"}) {
        const auto result=run(variant,analysis,rate,requested,published);
        const auto& starts=result.map.starts();
        check(starts.size()==half.starts().size(),"Map length changed");
        for (std::size_t i=1;i<starts.size();++i)
            check(starts[i]>starts[i-1],"Non-monotonic variable map");
        for (std::size_t x=0;x<analysis.inputFrames();x+=128)
            if (half.outputPositionForInputSample(double(x))<published)
                check(result.map.outputPositionForInputSample(double(x))==
                      half.outputPositionForInputSample(double(x)),
                      "Published output coordinate moved");
        const auto hops=measure(result.map);
        check(std::all_of(hops.invalid.begin(),hops.invalid.end(),
                          [](auto count){return count==0;}),"Unsafe synthesis hop");
        const auto disturbed=eventDisturbances(analysis,result.map,half,
                                                reference.fixedThreeQuarter());
        check(disturbed==0,"Protected event has interpolated hop");
        double startDelay=-1,completion=-1,partialElapsed=-1;
        long long startOutput=-1;
        if (result.changed) {
            for (std::size_t i=0;i<=result.firstChange;++i)
                check(starts[i]==half.starts()[i],"Pre-application coordinate moved");
            startOutput=starts[result.firstChange];
            startDelay=1000.0*(startOutput-requestOutput)/rate;
            check(startDelay>=0,"Transition began before request");
            if (result.complete) {
                check(result.completion>=result.firstChange,"Completion before start");
                completion=1000.0*(starts[result.completion]-startOutput)/rate;
            } else {
                partialElapsed=1000.0*(starts.back()-startOutput)/rate;
            }
        } else {
            check(starts==half.starts(),"Unapplied request modified the map");
        }
        std::cout<<name<<'\t'<<variant<<'\t'<<position<<'\t'<<requested<<'\t'
                 <<requestOutput<<'\t'<<published<<'\t'<<fifoAhead<<'\t'
                 <<result.status<<'\t'<<startOutput<<'\t'<<startDelay<<'\t'
                 <<completion<<'\t'<<partialElapsed<<'\t'<<result.paused<<'\t'
                 <<disturbed<<'\t'
                 <<hops.minimum[0]<<'\t'<<hops.maximum[0]<<'\t'
                 <<hops.minimum[1]<<'\t'<<hops.maximum[1]<<'\t'
                 <<hops.minimum[2]<<'\t'<<hops.maximum[2]<<'\n';
    }
}
void study(const std::string& name,const ts::Phase13TransientAnalysis& analysis,
    std::uint32_t rate) {
    VariableTimeMap baseline(analysis,rate);
    const auto length=analysis.inputFrames();
    scenario(name,analysis,rate,"head",2048,0);
    scenario(name,analysis,rate,"middle",(length/2/1024)*1024,0);
    scenario(name,analysis,rate,"tail",length-rate/4,0);
    if (!analysis.events().empty()) {
        const auto peak=analysis.events()[analysis.events().size()/2].peakFrame*1024;
        if (peak>1024 && peak+1024<length) {
            scenario(name,analysis,rate,"before",peak-1024,0);
            scenario(name,analysis,rate,"on",peak,0);
            scenario(name,analysis,rate,"after",peak+1024,0);
        }
    }
    const auto fifoInput=length/3;
    for (std::size_t ahead:{std::size_t{0},std::size_t{4096},
                            std::size_t{16384},std::size_t{32768}})
        scenario(name,analysis,rate,"fifo",fifoInput,ahead);
    std::cerr<<"fixed "<<name<<" 0.50="<<digest(baseline.fixedHalf().starts())
             <<" 0.75="<<digest(baseline.fixedThreeQuarter().starts())<<'\n';
}
}
int main(int argc,char** argv) {
    const auto scratch=std::filesystem::temp_directory_path()/
        ("phase22b_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(scratch);
    try {
        constexpr std::size_t length=48000*6;
        std::vector<float> left(length),right(length);
        for (std::size_t i=24000;i<length;i+=24000) left[i]=right[i]=0.8f;
        const float* audio[]={left.data(),right.data()};
        const auto click=scratch/"click.wav";
        {
            ts::WavStreamWriter writer(click,48000,2,length);
            writer.write(audio,length);
            writer.finish();
        }
        std::cout<<"source\tvariant\tposition\trequest_input\trequest_output\t"
                    "published_output\tfifo_ahead\tstatus\tstart_output\t"
                    "start_delay_ms\tcompletion_ms\tpartial_elapsed_ms\t"
                    "paused_intervals\tprotected_disturbances\t"
                    "low_min\tlow_max\tmid_min\tmid_max\thigh_min\thigh_max\n";
        const auto analyzed=ts::Phase13StreamingEngine(frozen(48000,2))
            .analyzeTransientEvents(click);
        study("click",analyzed,48000);
        if (argc==2) {
            const auto root=std::filesystem::path(argv[1])/"results/phase12/golden/input";
            for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
                const auto path=root/(std::string(name)+".wav");
                ts::WavStreamReader reader(path);
                const auto data=ts::Phase13StreamingEngine(
                    frozen(reader.sampleRate(),reader.channels()))
                    .analyzeTransientEvents(path);
                study(name,data,reader.sampleRate());
            }
        }
        std::filesystem::remove_all(scratch);
        return 0;
    } catch (const std::exception& e) {
        std::cerr<<"Phase 22B: "<<e.what()<<" (scratch: "<<scratch<<")\n";
        return 1;
    }
}
