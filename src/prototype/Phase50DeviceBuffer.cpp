#include <CoreAudio/CoreAudio.h>
#include <cstdlib>
#include <iostream>
int main(int argc,char** argv) {
    AudioDeviceID device=0;UInt32 bytes=sizeof(device);
    AudioObjectPropertyAddress address{kAudioHardwarePropertyDefaultOutputDevice,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject,&address,0,nullptr,&bytes,&device)!=noErr || !device) return 1;
    address.mSelector=kAudioDevicePropertyBufferFrameSize;
    UInt32 value=0;bytes=sizeof(value);
    if (AudioObjectGetPropertyData(device,&address,0,nullptr,&bytes,&value)!=noErr) return 1;
    std::cout<<"device_id="<<device<<"\nbuffer_frames="<<value<<'\n';
    if (argc==2) {
        auto requested=std::strtoul(argv[1],nullptr,10);
        if (requested!=64 && requested!=128 && requested!=256 && requested!=512 && requested!=1024) return 2;
        value=static_cast<UInt32>(requested);
        auto error=AudioObjectSetPropertyData(device,&address,0,nullptr,sizeof(value),&value);
        std::cout<<"set_status="<<error<<'\n';return error ? 1 : 0;
    }
    return argc==1 ? 0 : 2;
}
