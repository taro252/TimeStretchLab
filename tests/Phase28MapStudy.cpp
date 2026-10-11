#include "audio/WavStream.h"
#include "prototype/Phase22VariableTimeMap.h"
#include "prototype/Phase28ArbitraryTimeMap.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>

namespace {
using namespace ts;
using namespace ts::prototype;
void check(bool okay,const char* message) {
    if (!okay) throw std::runtime_error(message);
}
std::uint64_t hashWord(std::uint64_t state,std::uint64_t word) {
    return (state^word)*1099511628211ULL;
}
std::uint64_t hashStarts(const TimeMap& map) {
    std::uint64_t hash=14695981039346656037ULL;
    for (auto value:map.starts()) hash=hashWord(hash,static_cast<std::uint64_t>(value));
    return hash;
}
std::uint64_t hashEvents(const std::vector<TransientEvent>& events) {
    std::uint64_t hash=14695981039346656037ULL;
    for (const auto& e:events)
        for (const auto word:{e.onsetFrame,e.peakFrame,e.attackEndFrame,e.endFrame})
            hash=hashWord(hash,word);
    return hash;
}
std::uint64_t hashResets(const Phase13TransientAnalysis& analysis,double ratio) {
    TransientEventMap map(analysis.detectorFrames(),analysis.activeFrameCount(),
                          1024,ratio,EventMapConfig{},analysis.events());
    std::vector<double> offsets;
    for (const auto& anchor:analysis.anchors()) offsets.push_back(anchor.sampleOffset);
    map.refineAnchors(offsets);
    std::uint64_t hash=14695981039346656037ULL;
    for (std::size_t i=0;i<map.starts().size();++i)
        hash=hashWord(hash,map.resetAt(i)?1:0);
    return hash;
}
StretchConfig config(std::uint32_t rate,int channels) {
    StretchConfig c;
    c.sampleRate=rate;c.channels=channels;c.timeRatio=2;
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
void valid(const Phase28ArbitraryTimeMap& map,const ArbitraryPlan& plan) {
    check(plan.applied(),"Arbitrary transition was not applied");
    check(map.monotonic(),"Arbitrary map is not monotonic");
    check(!map.touchesProtected(plan),"Arbitrary ramp touches protected event");
    for (const auto& range:map.measureHops())
        check(range.minimum>0 && range.nonPositive==0 && range.outsideWindow==0,
              "Synthesis hop exceeds OLA window");
}
void run(const std::filesystem::path& path) {
    WavStreamReader reader(path);
    const auto analysis=Phase13StreamingEngine(config(reader.sampleRate(),
        static_cast<int>(reader.channels()))).analyzeTransientEvents(path);
    auto half=DecimalSpeed::fromDouble(0.50);
    Phase28ArbitraryTimeMap prototype(analysis,reader.sampleRate(),half);
    const VariableTimeMap old(analysis,reader.sampleRate());
    check(prototype.fixed(half).starts()==old.fixedHalf().starts(),"0.50 fixed map changed");
    const auto threeQuarter=DecimalSpeed::fromDouble(0.75);
    check(prototype.fixed(threeQuarter).starts()==old.fixedThreeQuarter().starts(),
          "0.75 fixed map changed");
    const auto eventHash=hashEvents(analysis.events());
    for (double value:{0.50,0.60,0.70,0.75,0.80}) {
        const auto speed=DecimalSpeed::fromDouble(value);
        const auto start=std::chrono::steady_clock::now();
        const auto& map=prototype.fixed(speed);
        const auto elapsed=std::chrono::duration<double,std::milli>(
            std::chrono::steady_clock::now()-start).count();
        const auto resetHash=hashResets(analysis,speed.timeRatio());
        std::cout<<path.stem().string()<<','<<value<<','<<hashStarts(map)<<','
                 <<eventHash<<','<<resetHash<<','<<analysis.events().size()<<','
                 <<elapsed<<','<<prototype.fixedMapBytes()<<'\n';
    }
    const auto speed60=DecimalSpeed::fromDouble(0.60);
    const auto speed70=DecimalSpeed::fromDouble(0.70);
    const auto speed80=DecimalSpeed::fromDouble(0.80);
    const auto n=reader.frames();
    for (const auto target:{speed60,speed70,speed80}) {
        Phase28ArbitraryTimeMap trial(analysis,reader.sampleRate(),half);
        const auto input=n/2;
        const auto published=static_cast<long long>(std::ceil(
            trial.current().outputPositionForInputSample(double(input))))+8192;
        const auto mark=std::chrono::steady_clock::now();
        const auto plan=trial.submit({1,target,input,published,50});
        const auto elapsed=std::chrono::duration<double,std::milli>(
            std::chrono::steady_clock::now()-mark).count();
        valid(trial,plan);
        std::cout<<"target_transition,"<<path.stem().string()<<','<<target.value()<<','
                 <<elapsed<<','<<trial.fixedMapBytes()<<','
                 <<plan.protectedEventsSkipped<<'\n';
    }
    if (n>reader.sampleRate()*3) {
        VariableTimeMap legacy(analysis,reader.sampleRate());
        Phase28ArbitraryTimeMap compatible(analysis,reader.sampleRate(),half);
        const auto input=n/3;
        const auto published=static_cast<long long>(std::ceil(
            compatible.current().outputPositionForInputSample(double(input))))+8192;
        const auto oldPlan=legacy.submit({1,input,published,50});
        const auto newPlan=compatible.submit({1,threeQuarter,input,published,50});
        check(oldPlan.applied && newPlan.applied(),"A50 compatibility request rejected");
        check(legacy.current().starts()==compatible.current().starts(),
              "Arbitrary prototype changed existing A50 transition");
    }
    for (auto input:{std::size_t{0},n/2,n>reader.sampleRate()?n-reader.sampleRate():n-1}) {
        Phase28ArbitraryTimeMap trial(analysis,reader.sampleRate(),half);
        const auto published=static_cast<long long>(std::ceil(
            trial.current().outputPositionForInputSample(double(input))))+8192;
        const auto before=trial.current().starts();
        const auto mark=std::chrono::steady_clock::now();
        const auto plan=trial.submit({1,speed70,input,published,50});
        const auto elapsed=std::chrono::duration<double,std::milli>(
            std::chrono::steady_clock::now()-mark).count();
        if (plan.applied()) {
            valid(trial,plan);
            check(std::equal(before.begin(),before.begin()+plan.appliedFrame+1,
                             trial.current().starts().begin()),"Published prefix changed");
        } else check(plan.outcome==ArbitraryOutcome::NoSafeInterval ||
                     plan.outcome==ArbitraryOutcome::Truncated,
                     "Unexpected terminal outcome");
        std::cout<<"transition,"<<path.stem().string()<<','<<input<<','
                 <<static_cast<int>(plan.outcome)<<','<<plan.appliedFrame<<','
                 <<plan.protectedEventsSkipped<<','<<elapsed<<','
                 <<trial.fixedMapBytes();
        if (plan.applied()) for (const auto& range:trial.measureHops())
            std::cout<<','<<range.minimum<<':'<<range.maximum;
        std::cout<<'\n';
    }
    if (n>reader.sampleRate()*3) {
        Phase28ArbitraryTimeMap trial(analysis,reader.sampleRate(),half);
        const auto input=n/4;
        const auto published=static_cast<long long>(std::ceil(
            trial.current().outputPositionForInputSample(double(input))))+8192;
        const auto first=trial.submit({1,speed60,input,published,50});
        valid(trial,first);
        const auto frozen=trial.current().starts();
        for (std::uint64_t generation=2;generation<=11;++generation)
            check(trial.submit({generation,speed80,input,
                first.appliedOutputSample+1,50}).outcome==ArbitraryOutcome::Busy,
                "Rapid in-flight request should be rejected");
        check(trial.current().starts()==frozen,"Rejected request changed the map");
        check(trial.submit({12,speed60,input,first.completionOutputSample,50}).outcome==
              ArbitraryOutcome::Duplicate,"Duplicate request not detected");
        check(trial.submit({11,speed80,input,first.completionOutputSample,50}).outcome==
              ArbitraryOutcome::Stale,"Stale generation not detected");
        const auto later=std::max(n*3/4,first.rampEndFrame*1024+2048);
        const auto fence=std::max(first.completionOutputSample,
            static_cast<long long>(std::ceil(trial.current().outputPositionForInputSample(
                double(later))))+8192);
        const auto second=trial.submit({13,speed80,later,fence,50});
        valid(trial,second);
        std::cout<<"two_changes,"<<path.stem().string()<<','<<first.appliedFrame<<','
                 <<second.appliedFrame<<','<<trial.fixedMapBytes()<<'\n';
        Phase28ArbitraryTimeMap reverse(analysis,reader.sampleRate(),speed80);
        const auto reverseInput=n/2;
        const auto reverseFence=static_cast<long long>(std::ceil(
            reverse.current().outputPositionForInputSample(double(reverseInput))))+8192;
        const auto reversePlan=reverse.submit({1,speed60,reverseInput,reverseFence,50});
        valid(reverse,reversePlan);
        if (path.stem()=="mix") {
            for (std::uint32_t micros=500000;micros<=1000000;micros+=25000)
                (void)trial.fixed({micros});
            check(trial.fixedMapBytes()<=6*trial.current().starts().size()*sizeof(long long),
                  "Arbitrary-speed map cache grew without a bound");
            std::cout<<"cache_bound,mix,"<<trial.fixedMapBytes()<<'\n';
        }
    }
    if (!analysis.events().empty()) {
        const auto at=analysis.events().front().peakFrame*1024;
        for (int shift:{-1024,0,1024}) {
            const auto input=shift<0 && at<static_cast<std::size_t>(-shift)
                ? 0 : static_cast<std::size_t>(static_cast<long long>(at)+shift);
            Phase28ArbitraryTimeMap trial(analysis,reader.sampleRate(),half);
            const auto published=static_cast<long long>(std::ceil(
                trial.current().outputPositionForInputSample(double(input))))+8192;
            const auto plan=trial.submit({1,speed70,input,published,50});
            if (plan.applied()) valid(trial,plan);
        }
    }
}
}
int main(int argc,char** argv) {
    try {
        for (double value:{0.0,-0.5,1.5,std::numeric_limits<double>::quiet_NaN(),
                          std::numeric_limits<double>::infinity(),0.60000001}) {
            bool rejected=false;
            try { (void)DecimalSpeed::fromDouble(value); }
            catch (const std::invalid_argument&) { rejected=true; }
            check(rejected,"Invalid speed accepted");
        }
        check(argc==2,"Repository path required");
        const auto folder=std::filesystem::path(argv[1])/"results/phase12/golden/input";
        std::cout<<"source,speed,map_hash,event_hash,reset_hash,events,fixed_ms,map_bytes\n";
        for (const char* name:{"mix","vocal","bass","drums","guitar"})
            run(folder/(std::string(name)+".wav"));
        const auto temp=std::filesystem::temp_directory_path()/
            ("phase28_map_"+std::to_string(
                std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directories(temp);
        constexpr std::size_t rate=48000;
        {
            std::vector<float> click(rate*12);
            for (std::size_t i=0;i<click.size();++i)
                click[i]=0.03f*std::sin(2.0*3.141592653589793*437.3*i/rate)+
                         (i%24000==0?0.8f:0.0f);
            const float* channels[]={click.data()};
            WavStreamWriter writer(temp/"click.wav",rate,1,click.size());
            writer.write(channels,click.size());writer.finish();
            run(temp/"click.wav");
        }
        {
            std::vector<float> tiny(2048);
            tiny[0]=0.5f;
            const float* channels[]={tiny.data()};
            WavStreamWriter writer(temp/"tiny.wav",rate,1,tiny.size());
            writer.write(channels,tiny.size());writer.finish();
            const auto analysis=Phase13StreamingEngine(config(rate,1)).analyzeTransientEvents(
                temp/"tiny.wav");
            Phase28ArbitraryTimeMap map(analysis,rate,DecimalSpeed::fromDouble(0.50));
            check(map.monotonic(),"Tiny input map is not monotonic");
            check(map.fixed(DecimalSpeed::fromDouble(0.80)).starts().size()==
                  map.current().starts().size(),"Tiny fixed map length differs");
            const auto outcome=map.submit({1,DecimalSpeed::fromDouble(0.70),
                tiny.size()-1,static_cast<long long>(map.current().starts().back()),50});
            check(!outcome.applied(),"Near-end tiny request should not apply");
            std::cout<<"tiny_input,2048,"<<static_cast<int>(outcome.outcome)<<'\n';
        }
        std::filesystem::remove_all(temp);
        rusage usage{};
        getrusage(RUSAGE_SELF,&usage);
        std::cout<<"peak_rss_bytes="<<usage.ru_maxrss<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 28 map study: "<<error.what()<<'\n';return 1;
    }
}
