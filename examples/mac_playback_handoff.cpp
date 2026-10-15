#include "platform/macos/MacPlaybackEngine.h"
#include <chrono>
#include <iostream>
#include <thread>
int main(int argc,char** argv) {
    if(argc!=2){std::cerr<<"Usage: playback_handoff_example input.wav\n";return 1;}
    using namespace ts::playback;
    try {
        MacPlaybackEngine player;
        auto cache=std::make_shared<PlaybackAnalysisCache>(32*1024*1024,64);
        auto candidate=Configuration::candidate(0.40);candidate.analysisCache=cache;
        MacOptions output;output.playbackGain=0.5f;output.seekFadeFrames=64;
        if(!player.prepare(argv[1],candidate,output)||!player.play())return 2;
        auto request=player.setSpeed(2.00); // Request ID, not an immediate audible change.
        std::this_thread::sleep_for(std::chrono::seconds(1));
        if(player.getPlaybackState()==PlaybackState::Playing){
            if(!player.pause()||!player.resume())return 2;
        }
        auto view=player.getStateSnapshot();
        std::cout<<"session="<<view.session<<" request="<<request<<" requested="<<view.requestedSpeed<<" target="<<view.appliedTargetSpeed<<'\n';
        // Input coordinates; completion is asynchronous. The old stream plays meanwhile.
        auto seekId=player.seekToInputSeconds(0.0);
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);
        for(;;){auto seek=player.getSeekSnapshot();
            if(seek.id==seekId&&seek.status==SeekStatus::Completed)break;
            if(seek.id==seekId&&(seek.status==SeekStatus::Failed||seek.status==SeekStatus::Rejected))return 2;
            if(std::chrono::steady_clock::now()>deadline)return 2;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));}
        std::cout<<"analysis_hit="<<player.getStartupDiagnostics().analysisHit<<'\n';
        player.stop();
        if(!player.prepare(argv[1],Configuration::baseline(0.50),output)||!player.play())return 2;
        while(player.getPlaybackState()==PlaybackState::Playing||player.getPlaybackState()==PlaybackState::Draining)
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        const auto d=player.getPlaybackDiagnostics();
        const auto state=player.getPlaybackState();player.stop();
        return state==PlaybackState::Ended&&d.missingFrames==0&&d.rejectedWrites==0&&d.error.empty()?0:2;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
