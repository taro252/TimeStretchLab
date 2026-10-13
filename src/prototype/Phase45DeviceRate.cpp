#include <CoreAudio/CoreAudio.h>
#include <iostream>
#include <cstdlib>
int main(int argc,char** argv) {
    AudioDeviceID device=0;UInt32 bytes=sizeof(device);
    AudioObjectPropertyAddress output{kAudioHardwarePropertyDefaultOutputDevice,
        kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject,&output,0,nullptr,&bytes,&device)!=noErr) return 1;
    AudioObjectPropertyAddress rate{kAudioDevicePropertyNominalSampleRate,
        kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
    Float64 value=0;bytes=sizeof(value);
    if (AudioObjectGetPropertyData(device,&rate,0,nullptr,&bytes,&value)!=noErr) return 1;
    std::cout<<"device_id="<<device<<"\nsample_rate="<<value<<'\n';
    if (argc==2) {
        const auto target=std::strtod(argv[1],nullptr);
        if (target!=44100 && target!=48000) return 2;
        value=target;
        const auto error=AudioObjectSetPropertyData(device,&rate,0,nullptr,sizeof(value),&value);
        std::cout<<"set_status="<<error<<'\n';return error ? 1 : 0;
    }
    return argc==1 ? 0 : 2;
}
