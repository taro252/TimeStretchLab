#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase58Diagnostics.h"
#include <CoreAudio/CoreAudio.h>
#include <fstream>
#include <iostream>
#include <thread>
using namespace ts::playback;using State=progressive::State;
namespace {
void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
AudioObjectPropertyAddress nominal(){return {kAudioDevicePropertyNominalSampleRate,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};}
double rate(AudioDeviceID device){double r=0;UInt32 size=sizeof(r);auto property=nominal();require(AudioObjectGetPropertyData(device,&property,0,nullptr,&size,&r)==noErr,"device rate query");return r;}
OSStatus change(AudioDeviceID device,double value){auto property=nominal();return AudioObjectSetPropertyData(device,&property,0,nullptr,sizeof(value),&value);}
void wait(ProgressiveMacPlaybackEngine& e,State target){const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(e.getPlaybackState()!=target){
    if(e.getPlaybackState()==State::Failed&&target!=State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);
    require(std::chrono::steady_clock::now()<end,"route state timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
}
// Explicit opt-in executable: temporarily changes the current output device's
// nominal rate, and restores that rate on every normal C++ exit path.
int main(int argc,char** argv){if(argc!=3)return 1;int result=1;std::thread control([&]{
    AudioDeviceID device=0;double original=0;OSStatus setStatus=-1,restoreStatus=-1;bool changed=false,stopped=false,restored=false;
    std::uint64_t seekId=0;std::string seekState,error;unsigned routes=0;
    try{
        ProgressiveMacPlaybackEngine e;ProgressiveOptions options;options.initialSpeed=.5;
        e.prepare(argv[1],options);wait(e,State::Ready);const auto native=e.getNativeDiagnostics();device=native.deviceId;original=rate(device);
        const double other=std::abs(original-48000)<1?44100:48000;
        auto property=nominal();Boolean writable=false;require(AudioObjectIsPropertySettable(device,&property,&writable)==noErr&&writable,"nominal rate is not settable");
        require(e.play(),"route play");std::this_thread::sleep_for(std::chrono::milliseconds(30));
        auto receipt=e.requestSeekToInputFrame(e.getPlaybackDiagnostics().inputFrames*4/5);require(receipt.accepted,"route seek");seekId=receipt.id;
        setStatus=change(device,other);require(setStatus==noErr,"nominal rate change failed");changed=true;
        const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);while(std::abs(rate(device)-other)>1&&std::chrono::steady_clock::now()<until)std::this_thread::sleep_for(std::chrono::milliseconds(10));
        require(std::abs(rate(device)-other)<1,"nominal rate did not change");
        wait(e,State::Stopped);stopped=e.getStateSnapshot().reason==StopReason::RouteChanged;routes=e.getNativeDiagnostics().routeChanges;
        for(const auto& op:e.seekHistory())if(op.id==seekId)seekState=progressive::name(op.state);
        require(stopped&&routes>0,"physical configuration change did not stop");e.stop();
        const auto d=e.getPlaybackDiagnostics();require(!d.pipeline.scheduling.active&&d.pipeline.scheduling.joins==d.pipeline.scheduling.restores,"route worker lifetime");
        result=0;
    }catch(const std::exception& ex){error=ex.what();}
    if(changed)try{restoreStatus=change(device,original);const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        while(restoreStatus==noErr&&std::abs(rate(device)-original)>1&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(10));
        restored=restoreStatus==noErr&&std::abs(rate(device)-original)<1;if(!restored)result=2;
    }catch(const std::exception& ex){result=2;error+="; restore: ";error+=ex.what();}
    std::ofstream f(argv[2]);f<<"{\"exit\":"<<result<<",\"device_id\":"<<device<<",\"original_rate\":"<<original<<",\"set_status\":"<<setStatus<<",\"changed\":"<<(changed?"true":"false")<<",\"safe_stopped\":"<<(stopped?"true":"false")<<",\"route_changes\":"<<routes<<",\"seek_id\":"<<seekId<<",\"seek_state\":\""<<seekState<<"\",\"restore_status\":"<<restoreStatus<<",\"restored\":"<<(restored?"true":"false")<<",\"error\":"<<ts::prototype::phase58::jsonString(error)<<"}\n";
    std::cout<<"route changed="<<changed<<" stopped="<<stopped<<" restored="<<restored<<" error="<<error<<'\n';
});control.join();return result;}
