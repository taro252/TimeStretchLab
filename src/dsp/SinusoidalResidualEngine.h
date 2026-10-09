#pragma once
#include "dsp/FFTAccelerate.h"
#include <complex>
#include <cstddef>
#include <filesystem>
#include <vector>

namespace ts {
enum class ResidualPhaseMode { Random, AnalysisContinuity };
struct SinusoidalResidualConfig {
    double sampleRate=48000;
    double timeRatio=1;
    std::size_t fftSize=4096;
    std::size_t analysisHop=512;
    std::size_t maximumTracksPerFrame=64;
    ResidualPhaseMode residualPhaseMode=ResidualPhaseMode::Random;
};
struct SinusoidalNode {
    std::size_t center=0;
    double frequencyHz=0;
    double amplitude=0;
    double analysisPhase=0;
};
struct SinusoidalTrack {
    int id=0;
    std::vector<SinusoidalNode> nodes;
    int missedFrames=0;
    bool active=true;
};
struct SinusoidalResidualStats {
    std::size_t frames=0;
    std::size_t trackBirths=0;
    std::size_t trackDeaths=0;
    double averageActiveTracks=0;
    double medianTrackLifetimeSeconds=0;
    double birthsPerSecond=0;
    double deathsPerSecond=0;
    double explainedEnergyRatio=0;
    double residualInputRmsRatio=0;
};
struct SinusoidalResidualResult {
    std::vector<float> output;
    std::vector<float> sinusoidalInput;
    std::vector<float> residualInput;
    std::vector<float> sinusoidalOutput;
    std::vector<float> residualOutput;
    SinusoidalResidualStats stats;
};

// Independent offline experiment. The track list and frame scheduler keep
// their identities separate from PhaseVocoder and WSOLA state.
class SinusoidalResidualEngine {
public:
    explicit SinusoidalResidualEngine(SinusoidalResidualConfig config);
    SinusoidalResidualResult processMono(const std::vector<float>& input,
        const std::filesystem::path& trackCsv={});
    const std::vector<SinusoidalTrack>& tracks() const { return tracks_; }
private:
    struct Peak {
        double frequencyHz=0,amplitude=0,phase=0,bin=0;
    };
    void analyze(const std::vector<float>& input);
    void renderSinusoids(std::vector<float>& output,double ratio) const;
    void synthesizeResidual(const std::vector<float>& residual,
                            std::vector<float>& output) const;
    void writeTracks(const std::filesystem::path& path) const;
    SinusoidalResidualConfig config_;
    FFTAccelerate fft_;
    std::vector<float> window_,frame_;
    std::vector<std::complex<float>> spectrum_;
    std::vector<SinusoidalTrack> tracks_;
    std::vector<std::vector<float>> masks_;
    std::size_t inputLength_=0,frameCount_=0,activeTrackSum_=0,births_=0,deaths_=0;
};
}
