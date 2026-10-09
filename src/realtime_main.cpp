#include "audio/WavStream.h"
#include "dsp/TimeStretchProcessor.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

int main(int argc,char** argv) {
    if (argc<7 || (argc-3)%2!=0) {
        std::cerr << "Usage: realtime_stretch input.wav output.wav --speed 0.75 "
                     "--mode linear|transient [--lookahead-ms 64|128|192] "
                     "[--phase-reset on|off] "
                     "[--events-csv path]\n";
        return 2;
    }
    try {
        double speed=0;std::string mode,eventCsv;unsigned lookahead=128;
        bool phaseReset=true;
        for (int i=3;i<argc;i+=2) {
            const std::string key=argv[i],value=argv[i+1];
            if (key=="--speed")speed=std::stod(value);
            else if (key=="--mode")mode=value;
            else if (key=="--lookahead-ms")lookahead=static_cast<unsigned>(std::stoul(value));
            else if (key=="--phase-reset") {
                if (value!="on" && value!="off")
                    throw std::invalid_argument("--phase-reset must be on or off");
                phaseReset=value=="on";
            }
            else if (key=="--events-csv")eventCsv=value;
            else throw std::invalid_argument("Unknown option: "+key);
        }
        if (!std::isfinite(speed) || speed<0.25 || speed>2 ||
            (mode!="linear" && mode!="transient") ||
            (mode=="linear" && !phaseReset))
            throw std::invalid_argument("Invalid speed or mode");
        ts::WavStreamReader reader(argv[1]);
        const auto expected=static_cast<std::size_t>(std::llround(reader.frames()/speed));
        ts::WavStreamWriter writer(argv[2],reader.sampleRate(),reader.channels(),expected);
        ts::TimeStretchProcessor processor;
        processor.prepare(reader.sampleRate(),static_cast<int>(reader.channels()),4096,
                          {mode=="transient",lookahead,phaseReset});
        processor.setSpeed(speed);
        std::array<std::array<float,4096>,2> input{},output{};
        std::size_t in=0,out=0;
        const auto begin=std::chrono::steady_clock::now();
        const auto drain=[&] {
            while (processor.availableOutputFrames()>0) {
                const auto count=std::min<std::size_t>(4096,processor.availableOutputFrames());
                float* pointers[]={output[0].data(),output[1].data()};
                const auto got=processor.pullOutput(pointers,count);
                const float* samples[]={output[0].data(),output[1].data()};
                writer.write(samples,got);out+=got;
            }
        };
        while (in<reader.frames()) {
            const auto count=std::min<std::size_t>(4096,reader.frames()-in);
            while (processor.availableInputCapacity()<count) {
                const auto produced=processor.process(4096);drain();
                if (processor.faulted() || (!produced && processor.availableInputCapacity()<count))
                    throw std::runtime_error("Streaming worker stalled");
            }
            for (std::size_t c=0;c<reader.channels();++c)
                for (std::size_t i=0;i<count;++i)input[c][i]=reader.sample(c,in+i);
            const float* pointers[]={input[0].data(),input[1].data()};
            if (processor.pushInput(pointers,count)!=count)
                throw std::runtime_error("Input FIFO overrun");
            in+=count;processor.process(4096);drain();
            if (processor.faulted())
                throw std::runtime_error("DSP failure at input="+std::to_string(in)+
                    " output="+std::to_string(out)+
                    " events="+std::to_string(processor.statistics().transientEvents)+
                    " code="+std::to_string(processor.statistics().dspFaultCode));
        }
        processor.signalEndOfInput();
        for (std::size_t attempts=0;!processor.drained() && attempts<1000000;++attempts) {
            processor.process(4096);drain();
            if (processor.faulted())throw std::runtime_error("DSP failure at EOS");
        }
        if (!processor.drained() || out!=expected)
            throw std::runtime_error("Incorrect output duration");
        writer.finish();
        const auto seconds=std::chrono::duration<double>(
            std::chrono::steady_clock::now()-begin).count();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto stats=processor.statistics();
        if (!eventCsv.empty()) {
            std::ofstream file(eventCsv);
            if (!file)throw std::runtime_error("Cannot write event CSV");
            file << "sequence,peakFrame,inputSample,strength,preciseAnchor\n";
            // The diagnostic ring retains the most recent 256 events.
            const auto start=stats.transientEvents>256?stats.transientEvents-256:0;
            for (auto i=start;i<stats.transientEvents;++i) {
                ts::RealtimeTransientEvent event;
                if (processor.transientEvent(i,event))
                    file << event.sequence << ',' << event.peakFrame << ','
                         << event.inputSample << ',' << event.strength << ','
                         << event.preciseAnchor << '\n';
            }
        }
        std::cout << "input_frames=" << in << " output_frames=" << out
                  << " lookahead_ms=" << (mode=="transient"?lookahead:0)
                  << " events=" << stats.transientEvents
                  << " anchors=" << stats.preciseAnchors
                  << " debt_samples=" << stats.stretchDebtSamples
                  << " maximum_debt_samples=" << stats.maximumAbsoluteDebtSamples
                  << " input_overrun_frames=" << stats.inputOverrunFrames
                  << " output_underrun_frames=" << stats.outputUnderrunFrames
                  << " processing_seconds=" << stats.processingNanoseconds/1e9
                  << " wall_seconds=" << seconds
                  << " peak_rss_bytes=" << usage.ru_maxrss << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';return 1;
    }
}
