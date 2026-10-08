#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <numbers>
#include <stdexcept>

int main() {
    try {
        constexpr int rate=44100;
        const auto base=std::filesystem::temp_directory_path()/"phase52_ablation";
        const auto input=base.string()+"_input.wav";
        const auto output=base.string()+"_output.wav";
        const auto control=base.string()+"_control.wav";
        ts::AudioBuffer audio{rate,std::vector<std::vector<float>>(2,std::vector<float>(rate*2))};
        for (std::size_t i=0;i<audio.channels[0].size();++i) {
            const auto sample=0.18*std::sin(2*std::numbers::pi*82.41*i/rate)+
                0.11*std::sin(2*std::numbers::pi*437.3*i/rate)+
                (i==rate/2 ? 0.5 : 0.0);
            audio.channels[0][i]=sample;
            audio.channels[1][i]=sample*0.8;
        }
        ts::WavWriter::write(input,audio);
        for (double speed:{0.75,0.5}) {
            ts::StretchConfig config;
            config.sampleRate=rate; config.channels=2; config.timeRatio=1/speed;
            config.enablePhaseLocking=true; config.enableTransientHandling=true;
            config.enableAdaptiveTimeMapping=true; config.enablePreciseTransientAnchoring=true;
            config.enableStereoCoherence=true; config.enableMultiResolution=true;
            ts::ChunkedTimeStretchEngine engine(config);
            const auto a=engine.processWav(input,output,16384,ts::AblationMode::MidOnly);
            const auto actualA=ts::WavReader::read(output);
            config.enableMultiResolution=false;
            ts::TimeStretchEngine reference(config);
            const auto expectedA=reference.processOffline(audio.channels);
            double maxA=0;
            for (int c=0;c<2;++c) for (std::size_t i=0;i<expectedA[c].size();++i)
                maxA=std::max(maxA,std::abs(double(expectedA[c][i])-actualA.channels[c][i]));
            if (maxA>=1e-5 || a.olaRingSamples!=32768 || a.firRingSamples!=0)
                throw std::runtime_error("A differs from Phase 4 single-resolution reference");
            config.enableMultiResolution=true;
            const auto b=engine.processWav(input,output,16384,ts::AblationMode::LowMid);
            const auto actualB=ts::WavReader::read(output);
            const auto c=engine.processWav(input,output,16384,ts::AblationMode::Full);
            const auto actualC=ts::WavReader::read(output);
            engine.processWav(input,control);
            const auto defaultC=ts::WavReader::read(control);
            double maxC=0;
            for (int ch=0;ch<2;++ch) for (std::size_t i=0;i<actualC.channels[ch].size();++i) {
                maxC=std::max(maxC,std::abs(double(actualC.channels[ch][i])-defaultC.channels[ch][i]));
                if (!std::isfinite(actualB.channels[ch][i])) throw std::runtime_error("B nonfinite");
            }
            if (maxC!=0 || a.timeMapHash!=b.timeMapHash || b.timeMapHash!=c.timeMapHash ||
                a.outputFrames!=b.outputFrames || b.outputFrames!=c.outputFrames ||
                b.olaRingSamples!=98304 || c.olaRingSamples!=106496 ||
                b.firRingSamples!=32768 || c.firRingSamples!=65536)
                throw std::runtime_error("A/B/C time map, length, or C regression mismatch");
            std::cout << "speed=" << speed << " A_vs_Phase4_max=" << maxA
                      << " C_vs_default_max=" << maxC << " time_map_hash=" << c.timeMapHash << '\n';
        }
        std::filesystem::remove(input); std::filesystem::remove(output); std::filesystem::remove(control);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
