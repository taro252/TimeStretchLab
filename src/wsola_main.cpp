#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/WSOLAEngine.h"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

namespace {
double number(const char* text) {
    std::size_t consumed=0;
    const double value=std::stod(text,&consumed);
    if (consumed!=std::string(text).size() || !std::isfinite(value))
        throw std::invalid_argument("Invalid numeric option");
    return value;
}
int integer(const char* text) {
    const double value=number(text);
    if (value<0 || value>16384 || std::floor(value)!=value)
        throw std::invalid_argument("Invalid integer option");
    return static_cast<int>(value);
}
}
int main(int argc,char** argv) {
    if (argc<5 || argc%2==0) {
        std::cerr << "Usage: wsola_stretch input.wav output.wav --speed 0.75 "
                     "[--window 2048] [--hop 512] [--search 512] [--debug-csv path]\n";
        return 2;
    }
    try {
        double speed=0;
        ts::WSOLAConfig config;
        std::filesystem::path csv;
        for (int i=3;i<argc;i+=2) {
            const std::string key=argv[i];
            if (key=="--speed") speed=number(argv[i+1]);
            else if (key=="--window") config.windowSize=integer(argv[i+1]);
            else if (key=="--hop") config.synthesisHop=integer(argv[i+1]);
            else if (key=="--search") config.searchRadius=integer(argv[i+1]);
            else if (key=="--debug-csv") csv=argv[i+1];
            else throw std::invalid_argument("Unknown option: "+key);
        }
        if (!(speed>0 && speed<=2)) throw std::invalid_argument("Invalid speed");
        auto input=ts::WavReader::read(argv[1]);
        config.sampleRate=input.sampleRate;
        config.timeRatio=1.0/speed;
        ts::WSOLAEngine engine(config);
        if (!csv.empty() && !csv.parent_path().empty())
            std::filesystem::create_directories(csv.parent_path());
        const auto start=std::chrono::steady_clock::now();
        auto output=engine.processOffline(input.channels,csv);
        const double seconds=std::chrono::duration<double>(
            std::chrono::steady_clock::now()-start).count();
        const auto outputFrames=output.empty() ? 0 : output[0].size();
        ts::WavWriter::write(argv[2],{input.sampleRate,std::move(output)});
        rusage resources{};
        getrusage(RUSAGE_SELF,&resources);
        const auto stats=engine.stats();
        std::cout << "outputFrames=" << outputFrames << " grains=" << stats.grainCount
                  << " avgAbsOffset=" << stats.averageAbsoluteOffset
                  << " p95AbsOffset=" << stats.p95AbsoluteOffset
                  << " avgCorrelation=" << stats.averageCorrelation
                  << " p10Correlation=" << stats.p10Correlation
                  << " processingSeconds=" << seconds
                  << " peakRSSBytes=" << resources.ru_maxrss << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
