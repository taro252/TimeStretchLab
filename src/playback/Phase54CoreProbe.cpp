// Verification only: stream/hash PCM without saving a stretched song.
#include "playback/PlaybackEngine.h"
#include <iostream>
using namespace ts::playback;
int main(int argc,char**argv){try{if(argc!=3)throw std::invalid_argument("input speed");PlaybackEngine e;auto cfg=Configuration::candidate(std::stod(argv[2]));cfg.verifyRawPcm=true;if(!e.prepare(argv[1],cfg)||!e.play())throw std::runtime_error(e.getPlaybackDiagnostics().error);
 std::array<std::array<float,4096>,2> b{};float* p[]={b[0].data(),b[1].data()};while(e.getPlaybackState()==PlaybackState::Playing){auto n=std::min<std::size_t>(4096,e.getPlaybackDiagnostics().fifoAvailable);if(n)e.renderAudio(p,n,1);else std::this_thread::sleep_for(std::chrono::microseconds(100));}
 auto d=e.getPlaybackDiagnostics();std::cout<<"state="<<name(e.getPlaybackState())<<"\neos="<<(e.getPlaybackState()==PlaybackState::Ended)<<"\nraw_pcm_sha256="<<e.rawPcmSha()<<"\nproduced_frames="<<d.producedFrames<<"\nconsumed_frames="<<d.consumedFrames<<"\nmissing_frames="<<d.missingFrames<<"\nworker_error="<<d.error<<'\n';return e.getPlaybackState()==PlaybackState::Ended&&!d.missingFrames&&d.error.empty()?0:2;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
