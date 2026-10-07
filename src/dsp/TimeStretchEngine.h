#pragma once
#include "dsp/OverlapAdd.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/STFT.h"
#include <vector>

namespace ts {
struct StretchConfig {
    double sampleRate = 44100.0;
    int channels = 2;
    double timeRatio = 1.0; // output duration / input duration
    // Reserved switches for later phases; Phase 1 requires all to be false.
    bool enablePhaseLocking = false;
    bool enableTransientHandling = false;
    bool enableMultiResolution = false;
    int fftSize = 4096;
    int analysisHop = 1024;
    float transientThreshold = 1.5f;
};

class TimeStretchEngine {
public:
    explicit TimeStretchEngine(const StretchConfig& config);
    void reset();
    void setTimeRatio(double ratio);
    std::vector<std::vector<float>> processOffline(const std::vector<std::vector<float>>& input);
    double synthesisHop() const { return config_.analysisHop * config_.timeRatio; }
private:
    StretchConfig config_;
    STFT stft_;
    std::vector<PhaseVocoder> vocoders_;
    std::vector<float> frame_, synthesized_;
    std::vector<std::complex<float>> spectrum_, stretchedSpectrum_;
};
}
