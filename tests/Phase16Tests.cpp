#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {
ts::StretchConfig frozen(const ts::WavStreamReader& input) {
    ts::StretchConfig c;
    c.sampleRate=input.sampleRate();
    c.channels=static_cast<int>(input.channels());
    c.timeRatio=2.0;
    c.enableMultiResolution=true;
    c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;
    c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}

struct Result {
    std::size_t samples=0,seeks=0,inputMidpoint=0,mappedOutputMidpoint=0;
    double maximum=0,seekSeconds=0,maximumSeekSeconds=0;
};
Result verify(const std::filesystem::path& inputPath,const std::filesystem::path& goldenPath) {
    ts::WavStreamReader input(inputPath),golden(goldenPath);
    if (input.channels()!=golden.channels() || input.sampleRate()!=golden.sampleRate() ||
        golden.frames()!=input.frames()*2)
        throw std::runtime_error("Golden metadata mismatch");
    ts::Phase14PlaybackPipeline pipeline(frozen(input));
    pipeline.prepare(inputPath);
    if (pipeline.outputFrames()!=golden.frames()) throw std::runtime_error("Output length mismatch");
    const auto mapped=pipeline.outputFrameForInputFrame(input.frames()/2);
    if (mapped>=golden.frames()) throw std::runtime_error("TimeMap seek outside output");
    bool rejected=false;
    try { pipeline.outputFrameForInputFrame(input.frames()+1); }
    catch (const std::out_of_range&) { rejected=true; }
    if (!rejected || pipeline.outputFrameForInputFrame(input.frames())!=golden.frames())
        throw std::runtime_error("TimeMap endpoint handling");
    std::size_t previousMapped=0;
    for (std::size_t i=0;i<input.frames();i+=std::max<std::size_t>(1,input.frames()/1000)) {
        const auto position=pipeline.outputFrameForInputFrame(i);
        if (position<previousMapped || position>=golden.frames())
            throw std::runtime_error("TimeMap seek coordinates are not ordered");
        previousMapped=position;
    }
    const auto oneSecond=static_cast<std::size_t>(input.sampleRate());
    const std::array<std::size_t,7> points={
        0,std::min<std::size_t>(golden.frames()-1,1023),
        golden.frames()/2,mapped,
        golden.frames()-std::min(golden.frames(),oneSecond),
        golden.frames()/3,golden.frames()/2+17};
    const std::array<std::size_t,7> blocks={64,128,256,512,1024,2048,4096};
    std::vector<std::vector<float>> scratch(input.channels(),std::vector<float>(4096));
    std::vector<float*> pointers(input.channels());
    for (std::size_t c=0;c<input.channels();++c) pointers[c]=scratch[c].data();
    Result result;
    result.inputMidpoint=input.frames()/2;
    result.mappedOutputMidpoint=mapped;
    for (const auto target:points) {
        const auto begin=std::chrono::steady_clock::now();
        pipeline.startAtOutputFrame(target,16384,std::chrono::seconds(120));
        const auto warmup=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
        result.seekSeconds+=warmup;
        result.maximumSeekSeconds=std::max(result.maximumSeekSeconds,warmup);
        if (pipeline.statistics().underrunFrames || pipeline.statistics().fifoRejectedWrites)
            throw std::runtime_error("Seek warmup FIFO error");
        std::size_t position=target,blockIndex=0;
        const auto end=std::min(golden.frames(),target+oneSecond/4);
        while (position<end) {
            const auto count=std::min({blocks[blockIndex++%blocks.size()],end-position,
                                       pipeline.availableOutputFrames()});
            if (!count) {
                if (pipeline.workerFinished()) throw std::runtime_error("Seek ran out of output");
                std::this_thread::sleep_for(std::chrono::microseconds(100));
                continue;
            }
            if (pipeline.pullAudio(pointers.data(),count)!=count)
                throw std::runtime_error("Seek playback underrun");
            for (std::size_t c=0;c<input.channels();++c)
                for (std::size_t i=0;i<count;++i) {
                    const auto difference=std::abs(double(scratch[c][i])-golden.sample(c,position+i));
                    result.maximum=std::max(result.maximum,difference);
                    ++result.samples;
                }
            position+=count;
        }
        pipeline.stop(); // Callback is quiescent before any FIFO/state reset.
        ++result.seeks;
    }
    // Several requests arrive before any callback consumes the previous seek.
    for (const auto target:{golden.frames()/4,golden.frames()/2,
                            golden.frames()-std::min(golden.frames(),oneSecond)}) {
        pipeline.startAtOutputFrame(target,16384,std::chrono::seconds(120));
        pipeline.stop();
        ++result.seeks;
    }
    const auto finalTarget=std::min<std::size_t>(golden.frames()-1,oneSecond/2);
    pipeline.startAtOutputFrame(finalTarget,16384,std::chrono::seconds(120));
    const auto immediate=std::min<std::size_t>(64,pipeline.availableOutputFrames());
    if (pipeline.pullAudio(pointers.data(),immediate)!=immediate || immediate!=64)
        throw std::runtime_error("Rapid seek final FIFO unavailable");
    for (std::size_t c=0;c<input.channels();++c)
        for (std::size_t i=0;i<immediate;++i) {
            result.maximum=std::max(result.maximum,
                std::abs(double(scratch[c][i])-golden.sample(c,finalTarget+i)));
            ++result.samples;
        }
    pipeline.stop();
    ++result.seeks;
    if (result.maximum!=0) throw std::runtime_error("Seek differed from Golden samples");
    return result;
}
}

int main(int argc,char** argv) {
    std::filesystem::path directory;
    try {
        if (argc!=1 && argc!=3) throw std::invalid_argument("Usage: phase16_tests [input.wav golden.wav]");
        std::filesystem::path input,golden;
        if (argc==3) { input=argv[1];golden=argv[2]; }
        else {
            directory=std::filesystem::temp_directory_path()/
                ("phase16_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
            std::filesystem::create_directories(directory);
            input=directory/"input.wav";golden=directory/"golden.wav";
            constexpr std::size_t frames=48000*3;
            std::array<std::vector<float>,2> signal={std::vector<float>(frames),std::vector<float>(frames)};
            for (std::size_t i=0;i<frames;++i) {
                const auto harmonic=0.2f*std::sin(2*3.141592653589793*437.3*i/48000.0);
                const auto click=(i==12000 || i==72000 || i==119000) ? 0.6f : 0.0f;
                signal[0][i]=harmonic+click;
                signal[1][i]=0.8f*harmonic+0.7f*click;
            }
            const float* values[]={signal[0].data(),signal[1].data()};
            ts::WavStreamWriter writer(input,48000,2,frames);
            writer.write(values,frames);
            writer.finish();
            ts::WavStreamReader reader(input);
            ts::WavStreamWriter reference(golden,48000,2,frames*2);
            ts::Phase13StreamingEngine(frozen(reader)).processFile(input,
                [&](const float* const* samples,std::size_t count){reference.write(samples,count);});
            reference.finish();
        }
        const auto result=verify(input,golden);
        std::cout << "phase16_seeks=" << result.seeks << " compared_samples=" << result.samples
                  << " max_abs_difference=" << result.maximum
                  << " input_midpoint=" << result.inputMidpoint
                  << " mapped_output_midpoint=" << result.mappedOutputMidpoint
                  << " total_seek_warmup_seconds=" << result.seekSeconds
                  << " max_seek_warmup_seconds=" << result.maximumSeekSeconds << '\n';
        if (!directory.empty()) std::filesystem::remove_all(directory);
    } catch (const std::exception& error) {
        std::cerr << "Phase 16: " << error.what() << '\n';
        return 1;
    }
}
