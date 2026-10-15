#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase56ReferenceData.h"
#include "prototype/Phase56ProgressiveAnalysis.h"
#include "audio/WavWriter.h"
#include <iostream>
#include <sstream>
#include <unistd.h>
using namespace ts;using namespace ts::prototype;
int main(){auto path=std::filesystem::temp_directory_path()/("phase56_modes_"+std::to_string(getpid())+".wav");try{
    AudioBuffer audio;audio.sampleRate=48000;audio.channels.resize(1,std::vector<float>(48000));
    for(std::size_t i=10001;i<48000;i+=7003)audio.channels[0][i]=.75f;WavWriter::write(path,audio);
    StretchConfig c;c.sampleRate=48000;c.channels=1;c.timeRatio=2;c.qualityMode=QualityMode::Experimental;
    c.enableMultiResolution=true;c.enablePhaseLocking=true;c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;
    auto analysis=Phase13StreamingEngine(c).analyzeTransientEvents(path);
    for(auto speed:phase56::speeds){Phase39TimeMap baseline(analysis,48000,Phase39Speed::fromDouble(speed),Phase39Planning::C);
        Phase39TimeMap candidate(analysis,48000,Phase39Speed::fromDouble(speed),Phase39Planning::L2);
        if(baseline.current().starts()!=candidate.current().starts())throw std::runtime_error("Initial fixed map differs by preset");}
    phase56::ProgressiveAnalysisSession ordered(48000,1,4,{},{2000000,410000,990000,1010000,400000});
    const float* orderedP[]={audio.channels[0].data()};ordered.appendInput(4,0,orderedP,48000);ordered.finishInput(4);
    auto orderedSnap=ordered.getSnapshot();
    for(std::size_t i=0;i<orderedSnap->speedCount;++i){const auto speed=orderedSnap->speedMicros[i];
        const auto expected=Phase39TimeMap(analysis,48000,Phase39Speed::fromDouble(double(speed)/1000000.)).current().starts();
        const auto& got=orderedSnap->mapForSpeed(speed);if(got.size()!=expected.size())throw std::runtime_error("Requested order size mismatch");
        for(std::size_t j=0;j<expected.size();++j)if(got.at(j)!=expected[j])throw std::runtime_error("Requested order changed speed map");
    }
    audio.channels[0].assign(32768,0);audio.channels[0][3001]=.75f;WavWriter::write(path,audio);
    analysis=Phase13StreamingEngine(c).analyzeTransientEvents(path);bool rejected=false;
    try{Phase39TimeMap invalid(analysis,48000,Phase39Speed::fromDouble(2.));}catch(const std::runtime_error&){rejected=true;}
    if(!rejected)throw std::runtime_error("Expected frozen high-speed rejection");
    phase56::ProgressiveAnalysisSession raw(48000,1,1,{},{}),slow(48000,1,2,{},{500000});const float* p[]={audio.channels[0].data()};
    raw.appendInput(1,0,p,32768);raw.finishInput(1);slow.appendInput(2,0,p,32768);slow.finishInput(2);
    phase56::ReferenceData expected{48000,1,analysis.inputFrames(),analysis.activeFrameCount(),analysis.transientCount(),analysis.detectorFrames(),analysis.events(),analysis.anchors(),{}};
    auto snap=raw.getSnapshot();auto copy=[](const auto& series){using T=std::remove_cvref_t<decltype(series.at(0))>;std::vector<T> v;for(std::size_t i=0;i<series.size();++i)v.push_back(series.at(i));return v;};
    phase56::ReferenceData actual{48000,1,snap->receivedInputFrames,snap->activeFrameCount,snap->transientCount,copy(snap->detector),copy(snap->events),copy(snap->anchors),{}};
    std::ostringstream a,b;phase56::write(a,expected);phase56::write(b,actual);if(a.str()!=b.str())throw std::runtime_error("Analysis-only rejected or differs on map-invalid input");
    auto mapped=Phase39TimeMap(analysis,48000,Phase39Speed::fromDouble(.5)).current().starts();
    if(copy(slow.getSnapshot()->mapForSpeed(500000))!=mapped||slow.getSnapshot()->speedCount!=1||snap->speedCount!=0)throw std::runtime_error("Selected speed map differs");
    bool missing=false;try{slow.getSnapshot()->mapForSpeed(2000000);}catch(const std::out_of_range&){missing=true;}
    if(!missing)throw std::runtime_error("Missing speed accepted");
    for(const auto& invalid:std::vector<std::vector<std::uint32_t>>{{399999},{2000001},{500000,500000},std::vector<std::uint32_t>(162,1000000)}){
        bool invalidRejected=false;try{phase56::MapPrefixBuilder map(invalid);}catch(const std::invalid_argument&){invalidRejected=true;}
        if(!invalidRejected)throw std::runtime_error("Invalid requested speeds accepted");
    }
    // Existing six-decimal speed semantics also work; the 161-step grid is not a bit mask.
    phase56::ProgressiveAnalysisSession fractional(48000,1,3,{},{666667});fractional.appendInput(3,0,p,32768);fractional.finishInput(3);
    if(copy(fractional.getSnapshot()->mapForSpeed(666667))!=Phase39TimeMap(analysis,48000,Phase39Speed::fromDouble(.666667)).current().starts())throw std::runtime_error("Six-decimal requested speed differs");
    std::filesystem::remove(path);std::cout<<"161 speeds: Baseline C / Candidate L2 initial fixed maps identical; transition planning remains separate PASS\n";return 0;
}catch(const std::exception& e){std::filesystem::remove(path);std::cerr<<e.what()<<'\n';return 1;}}
