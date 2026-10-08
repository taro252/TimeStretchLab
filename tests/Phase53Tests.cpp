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
        constexpr int rate=48000;
        const auto base=std::filesystem::temp_directory_path()/"phase53_quality";
        const auto inputPath=base.string()+"_in.wav";
        const auto outputPath=base.string()+"_out.wav";
        const auto referencePath=base.string()+"_reference.wav";
        ts::AudioBuffer input{rate,std::vector<std::vector<float>>(2,std::vector<float>(rate*2))};
        for (std::size_t i=0;i<input.channels[0].size();++i) {
            const auto t=double(i)/rate;
            input.channels[0][i]=0.2f*std::sin(2*std::numbers::pi*82.41*t)+
                0.08f*std::sin(2*std::numbers::pi*3700*t)+(i==rate/2?0.4f:0.0f);
            input.channels[1][i]=0.7f*input.channels[0][i];
        }
        ts::WavWriter::write(inputPath,input);
        for (double speed:{0.75,0.5}) for (const auto mode:{ts::QualityMode::Normal,
                ts::QualityMode::High,ts::QualityMode::Experimental}) {
            ts::StretchConfig config;
            config.sampleRate=rate; config.channels=2; config.timeRatio=1/speed;
            config.enablePhaseLocking=true; config.enableTransientHandling=true;
            config.enableAdaptiveTimeMapping=true; config.enablePreciseTransientAnchoring=true;
            config.enableStereoCoherence=true;
            config.enableMultiResolution=mode!=ts::QualityMode::Normal;
            config.qualityMode=mode;
            const auto explicitMode=mode==ts::QualityMode::Normal ? ts::AblationMode::MidOnly :
                mode==ts::QualityMode::High ? ts::AblationMode::LowMid : ts::AblationMode::Full;
            ts::ChunkedTimeStretchEngine stream(config);
            const auto stats=stream.processWav(inputPath,outputPath);
            const auto actual=ts::WavReader::read(outputPath);
            stream.processWav(inputPath,referencePath,16384,explicitMode);
            const auto explicitOutput=ts::WavReader::read(referencePath);
            const auto offline=ts::TimeStretchEngine(config).processOffline(input.channels);
            double exact=0,offlineDifference=0;
            if (actual.channels[0].size()!=stats.outputFrames ||
                stats.outputFrames!=std::size_t(std::llround(input.channels[0].size()/speed)))
                throw std::runtime_error("Quality mode duration mismatch");
            for (int c=0;c<2;++c) for (std::size_t i=0;i<stats.outputFrames;++i) {
                const auto value=actual.channels[c][i];
                if (!std::isfinite(value)) throw std::runtime_error("Nonfinite sample");
                exact=std::max(exact,std::abs(double(value)-explicitOutput.channels[c][i]));
                offlineDifference=std::max(offlineDifference,std::abs(double(value)-offline[c][i]));
            }
            if (exact!=0 || offlineDifference>=1e-5)
                throw std::runtime_error("Quality mode disagrees with Phase 5.2 or offline path");
            std::cout << "speed=" << speed << " quality=" << int(mode)
                      << " exact=" << exact << " offline_difference=" << offlineDifference << '\n';
        }
        std::filesystem::remove(inputPath);
        std::filesystem::remove(outputPath);
        std::filesystem::remove(referencePath);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
