#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>

namespace {
using namespace ts;
using Clock=std::chrono::steady_clock;
constexpr std::array<int,3> windows{8192,4096,1024};
constexpr std::array<int,3> hops{2048,1024,256};
constexpr std::array<double,17> speeds{0.25,0.30,0.35,0.40,0.45,
    0.50,0.60,0.70,0.75,0.80,0.90,1.00,1.10,1.25,1.50,1.75,2.00};

StretchConfig frozen(std::uint32_t rate,int channels,double ratio) {
    StretchConfig c;
    c.sampleRate=rate;c.channels=channels;c.timeRatio=ratio;
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
struct Schedule {
    std::vector<long long> starts;
    std::size_t frames=0,inserted=0,atMax=0;
    long long minimum=std::numeric_limits<long long>::max(),maximum=0;
    long long firstOutsideOutput=-1;
    std::size_t nonpositive=0,outside=0,aboveHalf=0;
    double minimumWeight=0,weakFraction=0;
};
Schedule measure(const TimeMap& map,std::size_t inputFrames,int window,int hop,
                 char mode,double ratio) {
    Schedule s;
    const int step=mode=='B' && ratio>2.0 ? hop/2 : hop;
    const auto padding=static_cast<std::size_t>(window/2);
    const auto frameCount=(inputFrames+padding+step-1)/step+1;
    std::vector<std::size_t> inputPositions;
    inputPositions.reserve(frameCount*(mode=='C' && ratio>2.0?2:1));
    for (std::size_t i=0;i<frameCount;++i) inputPositions.push_back(i*step);
    if (mode=='C' && ratio>2.0) {
        std::vector<std::size_t> expanded;
        expanded.reserve(inputPositions.size()*2);
        for (std::size_t i=0;i<inputPositions.size();++i) {
            const auto first=inputPositions[i];
            expanded.push_back(first);
            if (i+1==inputPositions.size()) continue;
            const auto last=inputPositions[i+1];
            const auto atFirst=std::llround(map.outputPositionForInputSample(double(first)));
            const auto atLast=std::llround(map.outputPositionForInputSample(double(last)));
            const auto parts=std::max(1LL,static_cast<long long>(std::ceil(
                double(atLast-atFirst)/(window/2.0))));
            for (long long part=1;part<parts;++part) {
                const auto input=first+static_cast<std::size_t>(
                    std::llround(double(last-first)*part/parts));
                if (input>expanded.back() && input<last) {
                    expanded.push_back(input);
                    ++s.inserted;
                }
            }
        }
        inputPositions=std::move(expanded);
    }
    s.starts.reserve(inputPositions.size());
    for (auto input:inputPositions)
        s.starts.push_back(std::llround(map.outputPositionForInputSample(double(input))));
    s.frames=s.starts.size();
    const auto outputLength=std::llround(
        map.outputPositionForInputSample(double(inputFrames)));
    for (std::size_t i=1;i<s.starts.size();++i) {
        const auto distance=s.starts[i]-s.starts[i-1];
        s.minimum=std::min(s.minimum,distance);
        if (distance>s.maximum) s.maximum=distance;
        if (s.starts[i-1]>window*4 && s.starts[i]<outputLength-window*4 &&
            (s.atMax==0 || distance>s.starts[s.atMax+1]-s.starts[s.atMax]))
            s.atMax=i-1;
        if (distance<=0) ++s.nonpositive;
        if (distance>=window) {
            ++s.outside;
            if (s.firstOutsideOutput<0) s.firstOutsideOutput=s.starts[i-1];
        }
        if (distance>window/2) ++s.aboveHalf;
    }
    if (s.minimum==std::numeric_limits<long long>::max()) s.minimum=0;
    if (s.starts.size()<4) return s;
    // Measure Hann² normalization in the worst interior hop. The same
    // floating-point threshold as RingOverlapAdd is included below.
    auto worst=s.atMax;
    const auto left=s.starts[worst];
    const auto right=s.starts[worst+1];
    if (right<=left || right-left>window*8LL) return s;
    std::vector<double> weight(static_cast<std::size_t>(right-left));
    auto first=std::lower_bound(s.starts.begin(),s.starts.end(),left-window+1)-s.starts.begin();
    for (std::size_t i=first;i<s.starts.size() && s.starts[i]<right;++i) {
        const auto begin=std::max(left,s.starts[i]);
        const auto end=std::min(right,s.starts[i]+window);
        for (auto at=begin;at<end;++at) {
            const auto n=at-s.starts[i];
            const auto hann=0.5*(1.0-std::cos(2.0*std::numbers::pi*n/window));
            weight[static_cast<std::size_t>(at-left)]+=hann*hann;
        }
    }
    s.minimumWeight=*std::min_element(weight.begin(),weight.end());
    s.weakFraction=double(std::count_if(weight.begin(),weight.end(),
        [](double value){return value<0.01;}))/weight.size();
    return s;
}
std::size_t peakRss() {
    rusage usage{};
    getrusage(RUSAGE_SELF,&usage);
    return static_cast<std::size_t>(usage.ru_maxrss);
}
TimeMap makeMap(const Phase13TransientAnalysis& analysis,double ratio,
                bool& anchorChanged,bool& protectionChanged,std::size_t& resets) {
    TransientEventMap timeline(analysis.detectorFrames(),analysis.activeFrameCount(),
        1024,ratio,EventMapConfig{},analysis.events());
    protectionChanged=false;
    for (std::size_t i=0;i<timeline.starts().size();++i) {
        if (timeline.starts()[i]!=std::llround(i*1024.0*ratio))
            protectionChanged=true;
    }
    const auto before=timeline.starts();
    std::vector<double> offsets;
    offsets.reserve(analysis.anchors().size());
    for (const auto& anchor:analysis.anchors()) offsets.push_back(anchor.sampleOffset);
    timeline.refineAnchors(offsets);
    anchorChanged=before!=timeline.starts();
    resets=0;
    for (std::size_t i=0;i<timeline.starts().size();++i)
        resets+=timeline.resetAt(i);
    return TimeMap(1024,timeline.starts(),timeline.events());
}
}

int main(int argc,char** argv) {
    if (argc!=3) {
        std::cerr<<"Usage: phase31_feasibility input.wav metrics.csv\n";
        return 2;
    }
    try {
        const std::filesystem::path input=argv[1],output=argv[2];
        WavStreamReader reader(input);
        const auto analysisStart=Clock::now();
        const auto analysis=Phase13StreamingEngine(frozen(reader.sampleRate(),
            static_cast<int>(reader.channels()),2.0)).analyzeTransientEvents(input);
        const auto analysisMs=std::chrono::duration<double,std::milli>(
            Clock::now()-analysisStart).count();
        std::ofstream csv(output);
        if (!csv) throw std::runtime_error("Cannot open metrics CSV");
        csv<<"source,speed,ratio,mode,resolution,window,analysis_hop,frames,inserted,"
              "output_frames,map_monotonic,events,resets,anchor_changed,protection_changed,"
              "hop_min,hop_max,worst_interior_hop,first_ge_window_output,"
              "nonpositive,ge_window,gt_half_window,"
              "min_hann2_weight_worst_gap,weak_fraction_worst_gap,"
              "analysis_ms,map_ms,schedule_ms,peak_rss_bytes\n";
        csv<<std::setprecision(12);
        for (const auto speed:speeds) {
            const auto ratio=1.0/speed;
            const auto mapStart=Clock::now();
            bool anchorChanged=false,protectionChanged=false;
            std::size_t resets=0;
            const auto map=makeMap(analysis,ratio,anchorChanged,protectionChanged,resets);
            const auto mapMs=std::chrono::duration<double,std::milli>(
                Clock::now()-mapStart).count();
            bool monotonic=true;
            for (std::size_t i=1;i<map.starts().size();++i)
                monotonic &= map.starts()[i]>map.starts()[i-1];
            const auto outputFrames=static_cast<std::size_t>(
                std::llround(reader.frames()*ratio));
            for (const char mode:{'A','B','C'}) for (std::size_t r=0;r<3;++r) {
                const auto start=Clock::now();
                const auto s=measure(map,reader.frames(),windows[r],hops[r],mode,ratio);
                const auto scheduleMs=std::chrono::duration<double,std::milli>(
                    Clock::now()-start).count();
                csv<<input.stem().string()<<','<<speed<<','<<ratio<<','<<mode<<','<<r<<','
                   <<windows[r]<<','<<(mode=='B' && ratio>2.0?hops[r]/2:hops[r])
                   <<','<<s.frames<<','
                   <<s.inserted<<','<<outputFrames<<','<<monotonic<<','
                   <<analysis.events().size()<<','<<resets<<','<<anchorChanged<<','
                   <<protectionChanged<<','<<s.minimum<<','<<s.maximum<<','
                   <<(s.starts.size()>1?s.starts[s.atMax+1]-s.starts[s.atMax]:0)<<','
                   <<s.firstOutsideOutput<<','
                   <<s.nonpositive<<','<<s.outside<<','<<s.aboveHalf<<','
                   <<s.minimumWeight<<','<<s.weakFraction<<','
                   <<analysisMs<<','<<mapMs<<','<<scheduleMs<<','<<peakRss()<<'\n';
            }
            std::cerr<<input.stem().string()<<" speed="<<speed
                     <<" ratio="<<ratio<<" map_ms="<<mapMs<<'\n';
        }
    } catch (const std::exception& e) {
        std::cerr<<"Phase 31 feasibility: "<<e.what()<<'\n';
        return 1;
    }
}
