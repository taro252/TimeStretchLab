// Phase55 only. Re-run the frozen analyser on growing WAV prefixes; never
// install a partial analysis into PlaybackEngine or copy a DSP algorithm.
#include "audio/WavStream.h"
#include "playback/PlaybackEngine.h"
#include "prototype/Phase45PcmDigest.h"
#include <bit>
#include <iomanip>
#include <iostream>
#include <stdexcept>

using namespace ts;
using namespace ts::playback;
using namespace ts::prototype;
namespace {
constexpr std::array speeds{.40,.50,.75,1.,1.25,1.50,2.};
void require(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); }
template<class T> bool bits(T a,T b) {
    if constexpr(sizeof(T)==4) return std::bit_cast<std::uint32_t>(a)==std::bit_cast<std::uint32_t>(b);
    else return std::bit_cast<std::uint64_t>(a)==std::bit_cast<std::uint64_t>(b);
}
bool same(const TransientFrame& a,const TransientFrame& b) {
    return bits(a.spectralFlux,b.spectralFlux)&&bits(a.logEnergy,b.logEnergy)&&
        bits(a.previousLogEnergy,b.previousLogEnergy)&&bits(a.threshold,b.threshold)&&
        bits(a.strength,b.strength)&&a.detected==b.detected&&a.resetApplied==b.resetApplied;
}
bool same(const TransientEvent& a,const TransientEvent& b) {
    return a.onsetFrame==b.onsetFrame&&a.peakFrame==b.peakFrame&&
        a.attackEndFrame==b.attackEndFrame&&a.endFrame==b.endFrame&&bits(a.strength,b.strength);
}
bool same(const TransientAnchor& a,const TransientAnchor& b) {
    return a.frame==b.frame&&bits(a.sampleOffset,b.sampleOffset)&&
        bits(a.absoluteInputSample,b.absoluteInputSample)&&bits(a.crestFactor,b.crestFactor)&&a.confident==b.confident;
}
StretchConfig frozen(const WavStreamReader& r) {
    StretchConfig c;c.sampleRate=r.sampleRate();c.channels=int(r.channels());c.timeRatio=2;
    c.qualityMode=QualityMode::Experimental;c.enableMultiResolution=true;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;return c;
}
std::string sha(const std::vector<float>& pcm,std::size_t samples) {
    Phase45PcmDigest d;
    // The digest API takes a 32-bit byte count per update.
    for(std::size_t p=0;p<samples;p+=16384) {
        const auto count=std::min<std::size_t>(16384,samples-p);
        d.update(pcm.data()+p,count*sizeof(float));
    }
    return d.finish();
}
std::vector<float> capture(const std::filesystem::path& path,double speed,Preset preset) {
    PlaybackEngine e;auto cfg=preset==Preset::Candidate?Configuration::candidate(speed):Configuration::baseline(speed);
    cfg.reuseAnalysis=false;
    require(e.prepare(path,cfg)&&e.play(),"PCM prepare/play failed");
    std::vector<float> pcm;
    const auto expected=e.getPlaybackDiagnostics().outputLength;
    pcm.reserve(expected*e.channels());
    std::array<std::array<float,4096>,2> b{};float* p[]{b[0].data(),b[1].data()};
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);
    while(e.getPlaybackState()==PlaybackState::Playing) {
        require(std::chrono::steady_clock::now()<deadline,"PCM drain timed out");
        const auto n=std::min<std::size_t>(4096,e.getPlaybackDiagnostics().fifoAvailable);
        if(!n){std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
        const auto got=e.renderAudio(p,n,1).received;
        for(std::size_t i=0;i<got;++i)for(std::size_t c=0;c<e.channels();++c)pcm.push_back(p[c][i]);
    }
    const auto d=e.getPlaybackDiagnostics();
    require(e.getPlaybackState()==PlaybackState::Ended&&d.missingFrames==0&&d.rejectedWrites==0&&d.error.empty(),"PCM EOS/supply failed");
    require(pcm.size()==expected*e.channels(),"PCM frame count differs from declared output length");
    return pcm;
}
long long firstMapDifference(const TimeMap& a,const TimeMap& b) {
    const auto n=std::min(a.starts().size(),b.starts().size());
    for(std::size_t i=0;i<n;++i)if(a.starts()[i]!=b.starts()[i])return static_cast<long long>(i);
    return -1;
}
}
int main(int argc,char** argv) {try {
    require(argc>=4,"Usage: phase55_analysis_probe map|pcm full.wav prefix.wav [...]");
    const bool pcm=std::string(argv[1])=="pcm";
    require(pcm||std::string(argv[1])=="map","Unknown mode");
    WavStreamReader reader(argv[2]);
    const auto full=Phase13StreamingEngine(frozen(reader)).analyzeTransientEvents(argv[2]);
    std::array<TimeMap,7> fullMaps;
    std::array<std::array<std::vector<float>,2>,7> fullPcm;
    for(std::size_t s=0;s<speeds.size();++s) {
        fullMaps[s]=Phase39TimeMap(full,reader.sampleRate(),Phase39Speed::fromDouble(speeds[s])).current();
        if(pcm)for(unsigned preset=0;preset<2;++preset)fullPcm[s][preset]=capture(argv[2],speeds[s],Preset(preset));
    }
    for(int arg=3;arg<argc;++arg) {
        WavStreamReader pr(argv[arg]);
        require(pr.sampleRate()==reader.sampleRate()&&pr.channels()==reader.channels()&&pr.frames()<=reader.frames(),"Prefix metadata invalid");
        // Verify every input sample, including sign-zero bits; a merely similar
        // fixture must never be described as a prefix of the reference.
        for(std::size_t i=0;i<pr.frames();++i)for(std::size_t c=0;c<pr.channels();++c)
            require(bits(pr.sample(c,i),reader.sample(c,i)),"Input is not an exact PCM prefix");
        const auto part=Phase13StreamingEngine(frozen(pr)).analyzeTransientEvents(argv[arg]);
        const bool eof=part.inputFrames()==full.inputFrames();
        const auto stable=eof?part.detectorFrames().size():
            (part.activeFrameCount()>2?part.activeFrameCount()-2:0);
        long long firstDetector=-1;
        for(std::size_t i=0;i<std::min(part.detectorFrames().size(),full.detectorFrames().size());++i)
            if(!same(part.detectorFrames()[i],full.detectorFrames()[i])){firstDetector=static_cast<long long>(i);break;}
        require(firstDetector<0||std::size_t(firstDetector)>=stable,"Stable detector frame changed");
        std::size_t sealed=0,through=0;
        for(std::size_t i=0;i<part.events().size();++i) {
            const auto& event=part.events()[i];
            if(!eof&&part.activeFrameCount()<=event.endFrame+12)break;
            require(i<full.events().size()&&same(event,full.events()[i]),"Sealed event changed");
            require(i<full.anchors().size()&&same(part.anchors()[i],full.anchors()[i]),"Sealed anchor changed");
            ++sealed;through=event.peakFrame;
        }
        long long firstEvent=-1,firstAnchor=-1;
        for(std::size_t i=0;i<part.events().size();++i) {
            if(firstEvent<0&&(i>=full.events().size()||!same(part.events()[i],full.events()[i])))firstEvent=static_cast<long long>(i);
            if(firstAnchor<0&&(i>=full.anchors().size()||!same(part.anchors()[i],full.anchors()[i])))firstAnchor=static_cast<long long>(i);
        }
        for(std::size_t s=0;s<speeds.size();++s) {
            const auto map=Phase39TimeMap(part,reader.sampleRate(),Phase39Speed::fromDouble(speeds[s])).current();
            const auto firstMap=firstMapDifference(map,fullMaps[s]);
            const auto provenNodes=eof?map.starts().size():(sealed?through+1:1);
            require(firstMap<0||std::size_t(firstMap)>=provenNodes,"Sealed map prefix changed");
            if(eof)require(map.starts()==fullMaps[s].starts()&&part.transientCount()==full.transientCount()&&part.events().size()==full.events().size(),"Final snapshot differs");
            for(unsigned preset=0;preset<(pcm?2u:1u);++preset) {
                long long firstPcm=-1;std::size_t common=0,safe=0,frames=0;
                std::string expectedSha,actualSha,safeExpected,safeActual;
                if(pcm) {
                    const auto got=capture(argv[arg],speeds[s],Preset(preset));
                    frames=got.size()/reader.channels();
                    common=std::min(got.size(),fullPcm[s][preset].size());
                    for(std::size_t i=0;i<common;++i)if(!bits(got[i],fullPcm[s][preset][i])){firstPcm=static_cast<long long>(i);break;}
                    // A deliberately conservative research crop, NOT a public
                    // DSP frontier proof or an adopted startup threshold.
                    safe=eof?frames:(sealed&&map.starts()[through]>16384?
                        std::min(frames,std::size_t(map.starts()[through]-16384)):0);
                    require(firstPcm<0||std::size_t(firstPcm)>=safe*reader.channels(),"Conservative sealed PCM crop changed");
                    require(!eof||(firstPcm<0&&got.size()==fullPcm[s][preset].size()),"EOF PCM differs");
                    expectedSha=sha(fullPcm[s][preset],common);actualSha=sha(got,common);
                    safeExpected=sha(fullPcm[s][preset],safe*reader.channels());safeActual=sha(got,safe*reader.channels());
                    require((expectedSha==actualSha)==(firstPcm<0)&&safeExpected==safeActual,"SHA/sample comparison inconsistency");
                }
                std::cout<<std::setprecision(17)<<"{\"prefix_index\":"<<arg-3<<",\"prefix_frames\":"<<part.inputFrames()
                    <<",\"full_frames\":"<<full.inputFrames()<<",\"eof\":"<<eof<<",\"speed\":"<<speeds[s]
                    <<",\"preset\":"<<preset<<",\"stable_detector_frames\":"<<stable<<",\"first_detector_difference\":"<<firstDetector
                    <<",\"partial_events\":"<<part.events().size()<<",\"sealed_events\":"<<sealed
                    <<",\"first_event_difference\":"<<firstEvent<<",\"first_anchor_difference\":"<<firstAnchor
                    <<",\"sealed_through_node\":"<<through<<",\"sealed_map_nodes\":"<<provenNodes
                    <<",\"first_map_difference\":"<<firstMap<<",\"first_map_input_sample\":"<<(firstMap<0?-1:firstMap*1024)
                    <<",\"partial_map_output\":"<<(firstMap<0?-1:map.starts()[firstMap])
                    <<",\"full_map_output\":"<<(firstMap<0?-1:fullMaps[s].starts()[firstMap])
                    <<",\"partial_output_frames\":"<<frames<<",\"common_pcm_frames\":"<<common/reader.channels()
                    <<",\"sealed_pcm_frames\":"<<safe<<",\"first_pcm_interleaved_sample\":"<<firstPcm
                    <<",\"first_pcm_frame\":"<<(firstPcm<0?-1:firstPcm/static_cast<long long>(reader.channels()))
                    <<",\"expected_common_sha256\":\""<<expectedSha<<"\",\"actual_common_sha256\":\""<<actualSha
                    <<"\",\"expected_sealed_sha256\":\""<<safeExpected<<"\",\"actual_sealed_sha256\":\""<<safeActual<<"\"}\n"<<std::flush;
            }
        }
    }
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
