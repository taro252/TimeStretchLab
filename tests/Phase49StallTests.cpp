#include "prototype/Phase39PlaybackPipeline.h"
#include "audio/WavWriter.h"
#include <cmath>
#include <thread>
#include <iostream>
#include <unistd.h>
using namespace ts;
using namespace ts::prototype;
int main() {
    const auto p=std::filesystem::temp_directory_path()/("phase49_stall_"+std::to_string(getpid())+".wav");
    AudioBuffer audio;audio.sampleRate=48000;audio.channels.resize(2,std::vector<float>(96000));
    for (std::size_t i=0;i<96000;++i) audio.channels[0][i]=audio.channels[1][i]=.2f*std::sin(2*3.141592653589793*437.3*i/48000);
    WavWriter::write(p,audio);
    unsetenv("PHASE45_WORKER_STALL_MS");
    setenv("PHASE49_STALL_MS","100",1);setenv("PHASE49_STALL_OUTPUT","8192",1);setenv("PHASE49_STALL_FIFO","8192",1);
    Phase39PlaybackPipeline pipeline(p,Phase39Speed::fromDouble(.4),16384,2048,12288,Phase39Planning::C,Phase39DensityDiagnostic::SafeGuarded,true);
    pipeline.start();
    // No consumption before the full lead: the intermediate 8192-stock trigger
    // is reached deterministically, independent of the test runner's load.
    if (!pipeline.waitForPrefill(12288,std::chrono::seconds(20)))
        throw std::runtime_error("Functional prefill failed");
    std::array<std::array<float,512>,2> block{};float* pointers[]={block[0].data(),block[1].data()};
    std::size_t consumed=0;
    while (!pipeline.drained()) {
        auto n=std::min<std::size_t>(512,pipeline.available());
        if (!n) { if (pipeline.finished()) pipeline.rethrowWorkerError();std::this_thread::sleep_for(std::chrono::microseconds(100));continue; }
        consumed+=pipeline.pullAudio(pointers,n);
    }
    pipeline.stop();pipeline.rethrowWorkerError();const auto info=pipeline.stallObservation();
    if (!info.triggered || info.fifoBefore!=8192 || info.wallSeconds<.1 || info.cancelled || consumed!=pipeline.snapshot().outputLength)
        throw std::runtime_error("Controlled FIFO stall/EOS regression");
    unsetenv("PHASE49_STALL_MS");unsetenv("PHASE49_STALL_OUTPUT");unsetenv("PHASE49_STALL_FIFO");
    std::filesystem::remove(p);
    std::cout<<"Functional injection detection PASS; this unpaced test is not realtime audio validation\n";
}
