#include "prototype/Phase36PlaybackPipeline.h"
#include <chrono>
#include <iostream>
#include <stdexcept>

using namespace ts::prototype;
static void require(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
int main(int argc,char** argv) {
    if (argc!=2) return 2;
    try {
        Phase36PlaybackPipeline pipeline(argv[1],{400000});
        require(pipeline.requestSpeed({500000},0)==Phase36RequestResult::Stopped,
                "Pre-start request accepted");
        pipeline.start();
        require(pipeline.waitForPrefill(4096,std::chrono::seconds(20)),"Prefill failed");
        require(pipeline.requestSpeed({399999},0)==Phase36RequestResult::Invalid,
                "Out-of-range speed accepted");
        require(pipeline.requestSpeed({400000},0)==Phase36RequestResult::Duplicate,
                "Duplicate speed accepted");
        require(pipeline.requestSpeed({500000},0)==Phase36RequestResult::Accepted,
                "Request rejected");
        require(pipeline.requestSpeed({450000},0)==Phase36RequestResult::Busy,
                "Overlapping request accepted");
        pipeline.stop();
        const auto stopped=pipeline.snapshot().state;
        require(stopped==Phase36RequestState::Cancelled ||
                stopped==Phase36RequestState::Rejected,
                "Stopped request not resolved");
        require(pipeline.requestSpeed({500000},0)==Phase36RequestResult::Stopped,
                "Stopped request accepted");
        pipeline.start();
        require(pipeline.waitForPrefill(4096,std::chrono::seconds(20)),"Restart prefill failed");
        pipeline.stop();
        std::cout<<"phase36 API start/stop/restart/request: passed\n";
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
