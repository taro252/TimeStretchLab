#include "audio/WavStream.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <sys/resource.h>
#include <vector>

// Independent measurement of the unchanged Phase 16 restart-and-discard seek.
int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::invalid_argument("input.wav golden.wav output.csv");
        ts::WavStreamReader input(argv[1]), golden(argv[2]);
        if (input.channels()!=golden.channels() || input.sampleRate()!=golden.sampleRate() ||
            golden.frames()!=input.frames()*2) throw std::runtime_error("Golden metadata mismatch");
        ts::StretchConfig config;
        config.sampleRate=input.sampleRate();
        config.channels=static_cast<int>(input.channels());
        config.timeRatio=2.0;
        config.enableMultiResolution=true;
        config.qualityMode=ts::QualityMode::Experimental;
        config.enablePhaseLocking=true;
        config.enableTransientHandling=true;
        config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=true;
        config.enableStereoCoherence=true;
        ts::Phase14PlaybackPipeline pipeline(config);
        pipeline.prepare(argv[1]);
        const auto total=golden.frames();
        const std::array<std::pair<const char*,double>,13> targets{{
            {"start",0.0},{"start",0.01},{"start",0.10},
            {"middle",0.45},{"middle",0.50},{"middle",0.55},
            {"end",0.90},{"end",0.95},{"end",0.99},
            {"rapid",0.75},{"rapid",0.25},{"rapid",0.80},{"rapid",0.15}}};
        std::ofstream csv(argv[3]);
        if (!csv) throw std::runtime_error("Cannot open CSV");
        csv << "kind,output_frame,warmup_seconds,cpu_seconds,max_abs_difference,peak_rss_bytes,underrun_frames,rejected_writes\n";
        std::vector<std::vector<float>> scratch(input.channels(),std::vector<float>(4096));
        std::vector<float*> planes(input.channels());
        for (std::size_t channel=0;channel<planes.size();++channel)
            planes[channel]=scratch[channel].data();
        double worst=0;
        for (const auto& [kind,fraction]:targets) {
            const auto frame=std::min(total-1,static_cast<std::size_t>(total*fraction));
            rusage before{},after{};
            getrusage(RUSAGE_SELF,&before);
            const auto begin=std::chrono::steady_clock::now();
            pipeline.startAtOutputFrame(frame,16384,std::chrono::seconds(120));
            const double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
            getrusage(RUSAGE_SELF,&after);
            const double cpu=(after.ru_utime.tv_sec-before.ru_utime.tv_sec)+
                (after.ru_utime.tv_usec-before.ru_utime.tv_usec)*1e-6+
                (after.ru_stime.tv_sec-before.ru_stime.tv_sec)+
                (after.ru_stime.tv_usec-before.ru_stime.tv_usec)*1e-6;
            const auto count=std::min<std::size_t>(4096,total-frame);
            if (pipeline.pullAudio(planes.data(),count)!=count)
                throw std::runtime_error("Insufficient FIFO after prefill");
            double difference=0;
            for (std::size_t channel=0;channel<planes.size();++channel)
                for (std::size_t i=0;i<count;++i)
                    difference=std::max(difference,std::abs(double(scratch[channel][i])-golden.sample(channel,frame+i)));
            worst=std::max(worst,difference);
            const auto stats=pipeline.statistics();
            csv << kind << ',' << frame << ',' << wall << ',' << cpu << ',' << difference << ','
                << after.ru_maxrss << ',' << stats.underrunFrames << ',' << stats.fifoRejectedWrites << '\n';
            pipeline.stop();
            if (difference!=0 || stats.underrunFrames || stats.fifoRejectedWrites)
                throw std::runtime_error("Golden mismatch or FIFO error");
        }
        std::cout << "seek_count=" << targets.size() << " max_abs_difference=" << worst << '\n';
    } catch (const std::exception& error) {
        std::cerr << "Phase 17 seek study: " << error.what() << '\n';
        return 1;
    }
}
