#include "prototype/Phase56ProgressiveAnalysis.h"
#include "prototype/Phase56ReferenceData.h"
#include "prototype/Phase56PinnedWav.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include "playback/StartupDiagnostics.h"
#include <bit>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase56;
namespace {
template<class T>void equal(T a,T b,const char* field,std::size_t i){
    std::uint64_t x,y;if constexpr(std::is_same_v<T,double>){x=std::bit_cast<std::uint64_t>(a);y=std::bit_cast<std::uint64_t>(b);}
    else if constexpr(std::is_same_v<T,float>){x=std::bit_cast<std::uint32_t>(a);y=std::bit_cast<std::uint32_t>(b);}
    else{x=std::uint64_t(a);y=std::uint64_t(b);}if(x!=y){std::ostringstream s;s<<field<<" index="<<i<<" actual_bits="<<std::hex<<x<<" reference_bits="<<y;throw std::runtime_error(s.str());}
}
void compare(const TransientFrame& a,const TransientFrame& b,std::size_t i){
    equal(a.spectralFlux,b.spectralFlux,"flux",i);equal(a.logEnergy,b.logEnergy,"energy",i);equal(a.previousLogEnergy,b.previousLogEnergy,"previousEnergy",i);equal(a.threshold,b.threshold,"threshold",i);equal(a.strength,b.strength,"strength",i);equal(a.detected,b.detected,"detected",i);equal(a.resetApplied,b.resetApplied,"reset",i);
}
void compare(const TransientEvent& a,const TransientEvent& b,std::size_t i){equal(a.onsetFrame,b.onsetFrame,"onset",i);equal(a.peakFrame,b.peakFrame,"peak",i);equal(a.attackEndFrame,b.attackEndFrame,"attackEnd",i);equal(a.endFrame,b.endFrame,"end",i);equal(a.strength,b.strength,"eventStrength",i);}
void compare(const TransientAnchor& a,const TransientAnchor& b,std::size_t i){equal(a.frame,b.frame,"anchorFrame",i);equal(a.sampleOffset,b.sampleOffset,"offset",i);equal(a.absoluteInputSample,b.absoluteInputSample,"absolute",i);equal(a.crestFactor,b.crestFactor,"crest",i);equal(a.confident,b.confident,"confidence",i);}
void check(const AnalysisSnapshot& s,const ReferenceData& r,std::size_t oldFrames,std::size_t oldEvents,std::size_t oldNodes){
    equal(s.speedCount,r.speedMicros.size(),"speedCount",0);
    for(std::size_t i=0;i<s.speedCount;++i)equal(s.speedMicros[i],r.speedMicros[i],"speedMicros",i);
    if(s.hasError||s.isCancelled)throw std::runtime_error("Unexpected error/cancel snapshot");
    if(s.detectorThrough>r.frames.size()||s.closedEventCount>r.events.size())throw std::runtime_error("Published past reference");
    for(auto i=oldFrames;i<s.detectorThrough;++i)compare(s.detector.at(i),r.frames[i],i);
    for(auto i=oldEvents;i<s.closedEventCount;++i){compare(s.events.at(i),r.events[i],i);compare(s.anchors.at(i),r.anchors[i],i);}
    for(std::size_t speed=0;speed<r.maps.size();++speed){if(s.maps[speed].size()>r.maps[speed].size())throw std::runtime_error("Map past reference");for(auto i=oldNodes;i<s.maps[speed].size();++i)equal(s.maps[speed].at(i),r.maps[speed][i],("map_"+std::to_string(speed)).c_str(),i);}
}
template<class T>std::vector<T> vector(const ImmutableSeries<T>& s){std::vector<T> v;v.reserve(s.size());for(std::size_t i=0;i<s.size();++i)v.push_back(s.at(i));return v;}
}
int main(int argc,char** argv){try{
    if(argc<5)throw std::invalid_argument("input.wav reference.bin chunk trace.csv [bench]");
    std::ifstream refFile(argv[2],std::ios::binary);auto ref=read(refFile);WavStreamReader reader(argv[1]);
    const bool bench=argc>5&&std::string(argv[5])=="bench";
    const bool irregular=std::string(argv[3])=="irregular";
    const auto chunk=irregular?131071:std::stoull(argv[3]);if(!chunk)throw std::invalid_argument("Zero chunk");
    const std::array<std::size_t,9> pattern{1,3071,17,8193,1023,131071,7,5003,65535};
    PinnedWavSource source(argv[1],71);
    struct Row{std::size_t received,feature,detector,events,nodes,copy;double wall,cpu;};std::vector<Row> rows;
    playback::StageClock total;
    ProgressiveAnalysisSession session(reader.sampleRate(),reader.channels(),71,{},ref.speedMicros);
    std::size_t at=0,iteration=0,oldFrames=0,oldEvents=0,oldNodes=0,nextHold=1,maxLag=0;
    std::vector<std::shared_ptr<const AnalysisSnapshot>> retained;
    double firstEvent=-1,firstMap=-1,lastMap=0,maxStall=0;
    while(at<reader.frames()){
        const auto n=std::min({irregular?pattern[iteration%pattern.size()]:std::size_t(chunk),reader.frames()-at,std::size_t(131072)});
        playback::StageClock clock;
        equal(source.appendNext(session,n),n,"source chunk",iteration);at+=n;++iteration;
        const auto elapsed=clock.elapsed();auto s=session.getSnapshot();auto now=total.elapsed().wallSeconds;
        equal(s->receivedInputFrames,at,"received",iteration);
        if(s->isFinal)throw std::runtime_error("Chunk mistaken for EOS");
        if(firstEvent<0&&s->closedEventCount)firstEvent=now;
        if(firstMap<0&&s->mapThroughNode>1)firstMap=now;
        if(s->mapThroughNode!=oldNodes){maxStall=std::max(maxStall,now-lastMap);lastMap=now;}
        const auto lastPeak=s->closedEventCount?s->events.at(s->closedEventCount-1).peakFrame*1024:0;
        maxLag=std::max(maxLag,at-lastPeak);
        if(!bench){check(*s,ref,oldFrames,oldEvents,oldNodes);
            if(s->featureThrough>=nextHold){retained.push_back(s);nextHold*=2;}}
        oldFrames=s->detectorThrough;oldEvents=s->closedEventCount;oldNodes=s->mapThroughNode;
        rows.push_back({at,s->featureThrough,s->detectorThrough,s->closedEventCount,s->mapThroughNode,session.statistics().snapshotCopyBytes,elapsed.wallSeconds,elapsed.threadCpuSeconds});
    }
    playback::StageClock finishing;source.finish(session);const auto finishTime=finishing.elapsed();const auto elapsed=total.elapsed();rusage usage{};getrusage(RUSAGE_SELF,&usage);auto final=session.getSnapshot();
    if(firstEvent<0&&final->closedEventCount)firstEvent=elapsed.wallSeconds;
    if(firstMap<0&&final->mapThroughNode>1)firstMap=elapsed.wallSeconds;
    maxStall=std::max(maxStall,elapsed.wallSeconds-lastMap);
    check(*final,ref,bench?0:oldFrames,bench?0:oldEvents,bench?0:oldNodes);
    equal(final->isFinal,true,"final",0);equal(final->inputGeneration,std::uint64_t(71),"generation",0);
    equal(final->receivedInputFrames,std::size_t(ref.input),"finalInput",0);equal(final->activeFrameCount,std::size_t(ref.active),"active",0);
    equal(final->transientCount,std::size_t(ref.transients),"transientCount",0);equal(final->detectorThrough,ref.frames.size(),"finalFrames",0);
    equal(final->closedEventCount,ref.events.size(),"finalEvents",0);equal(final->closedAnchorCount,ref.anchors.size(),"finalAnchors",0);
    for(auto& old:retained)check(*old,ref,0,0,0);
    ReferenceData actual{reader.sampleRate(),reader.channels(),final->receivedInputFrames,final->activeFrameCount,final->transientCount,vector(final->detector),vector(final->events),vector(final->anchors),{},{}};
    actual.speedMicros=ref.speedMicros;actual.maps.resize(ref.maps.size());
    for(std::size_t i=0;i<ref.maps.size();++i){equal(final->maps[i].size(),ref.maps[i].size(),"finalMapSize",i);actual.maps[i]=vector(final->maps[i]);}
    std::ostringstream encoded(std::ios::binary);write(encoded,actual);const auto bytes=encoded.str();Phase45PcmDigest hash;hash.update(bytes.data(),bytes.size());
    auto stats=session.statistics();equal(stats.fftFrames,ref.frames.size(),"FFT exactly once",0);
    equal(stats.mapIntervalWork,ref.frames.empty()?std::size_t(0):ref.frames.size()-1,"map intervals exactly once",0);
    std::ofstream trace(argv[4]);trace<<"received,feature,detector,events,map_nodes,snapshot_copy_bytes,snapshot_delta_copy_bytes,pcm_delta_copy_bytes,wall_s,cpu_s,is_final\n"<<std::setprecision(17);
    std::size_t previousCopy=0,previousInput=0;
    for(const auto& r:rows){trace<<r.received<<','<<r.feature<<','<<r.detector<<','<<r.events<<','<<r.nodes<<','<<r.copy<<','<<r.copy-previousCopy<<','<<(r.received-previousInput)*reader.channels()*sizeof(float)<<','<<r.wall<<','<<r.cpu<<",0\n";previousCopy=r.copy;previousInput=r.received;}
    trace<<final->receivedInputFrames<<','<<final->featureThrough<<','<<final->detectorThrough<<','<<final->closedEventCount<<','<<final->mapThroughNode<<','<<stats.snapshotCopyBytes<<','<<stats.snapshotCopyBytes-previousCopy<<",0,"<<finishTime.wallSeconds<<','<<finishTime.threadCpuSeconds<<",1\n";
    std::cout<<std::setprecision(17)<<"{\"PASS\":true,\"bench\":"<<bench<<",\"chunks\":"<<rows.size()<<",\"input_frames\":"<<ref.input
        <<",\"speed_count\":"<<ref.maps.size()<<",\"wall_seconds\":"<<elapsed.wallSeconds<<",\"thread_cpu_seconds\":"<<elapsed.threadCpuSeconds
        <<",\"finish_wall_seconds\":"<<finishTime.wallSeconds<<",\"finish_cpu_seconds\":"<<finishTime.threadCpuSeconds
        <<",\"first_closed_event_seconds\":"<<firstEvent<<",\"first_map_interval_seconds\":"<<firstMap
        <<",\"max_no_map_advance_seconds\":"<<maxStall<<",\"max_unclosed_input_frames\":"<<maxLag
        <<",\"fft_frames\":"<<stats.fftFrames<<",\"map_intervals\":"<<stats.mapIntervalWork
        <<",\"snapshot_live_bytes\":"<<stats.snapshotLiveBytes<<",\"snapshot_peak_bytes\":"<<stats.snapshotPeakBytes
        <<",\"snapshot_copy_bytes\":"<<stats.snapshotCopyBytes<<",\"pcm_copy_bytes\":"<<stats.pcmCopyBytes
        <<",\"working_bytes_estimate\":"<<stats.workingBytes<<",\"peak_rss_bytes\":"<<usage.ru_maxrss
        <<",\"retained_snapshots_checked\":"<<retained.size()<<",\"final_sha256\":\""<<hash.finish()<<"\"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
