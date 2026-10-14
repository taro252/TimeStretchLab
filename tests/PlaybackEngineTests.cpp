#include "playback/PlaybackEngine.h"
#include "audio/WavWriter.h"
#include <iostream>
#include <cmath>
#include <unistd.h>
#include <cstdlib>
#include <new>
#include <algorithm>
using namespace ts;using namespace ts::playback;
thread_local bool counting=false;std::atomic<unsigned> renderAllocations{0};
void* operator new(std::size_t n){if(counting)++renderAllocations;if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}void* operator new[](std::size_t n){return ::operator new(n);}void operator delete(void*p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void require(bool v,const char*s){if(!v)throw std::runtime_error(s);}
std::vector<float> drain(PlaybackEngine& e,bool withPause=false){
    std::array<std::array<float,4096>,2> block{};float* ptr[]={block[0].data(),block[1].data()};std::vector<float> result;bool paused=false;std::size_t chunk=0;
    while(e.getPlaybackState()==PlaybackState::Playing){auto n=std::min<std::size_t>(std::array<std::size_t,6>{64,128,256,512,1024,4096}[chunk%6],e.getPlaybackDiagnostics().fifoAvailable);if(!n){std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
        counting=true;auto r=e.renderAudio(ptr,n,1234);counting=false;for(std::size_t i=0;i<r.received;++i)for(std::size_t c=0;c<e.channels();++c)result.push_back(ptr[c][i]);++chunk;
        if(withPause&&!paused&&result.size()>20000){require(e.pause(),"pause");auto before=e.getCurrentPlaybackPosition();counting=true;auto silence=e.renderAudio(ptr,512,5678);counting=false;require(silence.received==0,"paused FIFO consumption");require(e.getCurrentPlaybackPosition().outputFrame==before.outputFrame,"pause position");for(auto& b:block)for(std::size_t i=0;i<512;++i)require(b[i]==0,"pause silence");std::this_thread::sleep_for(std::chrono::milliseconds(10));require(e.resume(),"resume");paused=true;}
    }
    require(e.getPlaybackState()==PlaybackState::Ended,"EOS state");require(e.getPlaybackDiagnostics().missingFrames==0,"unpaced supply");require(e.getPlaybackDiagnostics().consumedFrames==e.getPlaybackDiagnostics().outputLength,"EOS length");return result;
}
int main(){try{
    const auto path=std::filesystem::temp_directory_path()/("playback_api_"+std::to_string(getpid())+".wav");AudioBuffer a;a.sampleRate=48000;a.channels.resize(2,std::vector<float>(48000*8));for(std::size_t i=0;i<a.channels[0].size();++i)for(unsigned c=0;c<2;++c)a.channels[c][i]=.13f*std::sin(2*3.141592653589793*437.3*i/48000+c*.4);WavWriter::write(path,a);
    auto c=Configuration::candidate();c.verifyRawPcm=true;require(c.leadFrames()==16384&&Configuration::baseline().leadFrames()==12288,"preset freeze");
    PlaybackEngine e;require(e.getPlaybackState()==PlaybackState::Empty,"empty");require(e.prepare(path,c)&&e.play(),"start");auto expected=drain(e);auto digest=e.rawPcmSha();require(!digest.empty(),"hash");
    require(e.play(),"restart EOS");auto paused=drain(e,true);require(paused==expected,"pause/resume raw PCM");
    e.stop();require(e.getPlaybackState()==PlaybackState::Stopped,"stop");require(e.play(),"restart stop");require(drain(e)==expected,"stop/restart PCM");
    for(double speed:{.39,2.01,.5000001,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()}){bool rejected=false;try{e.setSpeed(speed);}catch(const std::invalid_argument&){rejected=true;}require(rejected,"invalid speed");}
    e.stop();require(e.prepare(path,Configuration::candidate(.4))&&e.play()&&e.pause(),"latest pause");auto id1=e.setSpeed(2);auto id2=e.setSpeed(.75);auto id3=e.setSpeed(1);require(e.getPendingSpeedChange()->id==id3,"latest wins");auto view=e.getStateSnapshot();require(view.state==PlaybackState::Paused&&view.pending->id==id3&&view.requestedSpeed==1&&view.appliedTargetSpeed==.4,"coherent UI snapshot");require(e.getRequestedSpeed()==1&&e.getAppliedTargetSpeed()==.4,"requested vs applied");auto h=e.operationHistory();require(std::count_if(h.begin(),h.end(),[&](auto&o){return (o.id==id1||o.id==id2)&&o.status==SpeedStatus::Replaced;})==2,"replaced history");e.stop();require(!e.getPendingSpeedChange()&&!e.getActiveSpeedChange(),"stop cancels commands");h=e.operationHistory();require(h.back().id==id3&&h.back().status==SpeedStatus::Cancelled,"cancel history");
    auto reject=Configuration::candidate(.4);reject.verificationHooks.forceRejectFirst=true;require(e.prepare(path,reject)&&e.play(),"reject fixture");e.setSpeed(2);for(unsigned i=0;i<3000;++i){h=e.operationHistory();if(!h.empty()&&h.back().status==SpeedStatus::Rejected)break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}require(h.back().status==SpeedStatus::Rejected,"terminal reject");auto next=e.setSpeed(1);drain(e);h=e.operationHistory();require(std::any_of(h.begin(),h.end(),[&](auto&o){return o.id==next&&o.status==SpeedStatus::Completed;}),"Rejected does not wedge pending");
    // Poison historical CLI variables. Typed application options must ignore all.
    setenv("PHASE45_WORKER_STALL_MS","not-a-number",1);setenv("PHASE49_STALL_MS","not-a-number",1);setenv("PHASE44_FORCE_NO_SAFE_FIRST","1",1);setenv("PHASE44_WORKER_QOS","1",1);
    e.stop();require(e.prepare(path,c)&&e.play(),"typed environment isolation");require(drain(e)==expected,"environment PCM");for(auto key:{"PHASE45_WORKER_STALL_MS","PHASE49_STALL_MS","PHASE44_FORCE_NO_SAFE_FIRST","PHASE44_WORKER_QOS"})unsetenv(key);
    e.stop();auto off=Configuration::candidate();require(!off.detailedDiagnostics,"diagnostic default off");require(e.prepare(path,off)&&e.play(),"underrun fixture");std::vector<float> l(65536),r(65536);float* pp[]={l.data(),r.data()};counting=true;e.renderAudio(pp,65536,9000);counting=false;e.pause();auto d=e.getPlaybackDiagnostics();require(d.missingFrames>0&&d.underrunCalls>0&&!e.underrunEvents().empty(),"diagnostic OFF fault detection");e.stop();
    require(renderAllocations==0,"callback C++ allocation");std::filesystem::remove(path);std::cout<<"API lifecycle/Latest-Wins/reject/EOF/typed config/zero render allocations PASS; deliberate underrun detected (audio FAIL fixture)\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
