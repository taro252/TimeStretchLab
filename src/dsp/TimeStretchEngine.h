#pragma once
#include "dsp/OverlapAdd.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/STFT.h"
#include "dsp/TransientDetector.h"
#include "dsp/TransientEventMap.h"
#include "dsp/TransientAnchor.h"
#include <string>
#include <vector>

namespace ts {
struct StretchConfig {
    double sampleRate = 44100.0;
    int channels = 2;
    double timeRatio = 1.0; // output duration / input duration
    // Reserved switches for later phases; Phase 1 requires all to be false.
    bool enablePhaseLocking = false;
    bool enableTransientHandling = false;
    bool enableAdaptiveTimeMapping = false;
    bool enableSelectivePhaseReset = false;
    bool enablePreciseTransientAnchoring = false;
    bool enableMultiResolution = false;
    int fftSize = 4096;
    int analysisHop = 1024;
    float transientThreshold = 1.5f;
    float transientSensitivity = 3.0f;
    float transientMinimumFlux = 0.02f;
    float transientStrengthThreshold = 0.25f;
    int transientHistoryFrames = 12;
    int transientCooldownFrames = 2;
    int transientLookbackFrames = 1;
    int eventMinimumDistanceFrames = 4;
    int eventDecayMergeFrames = 12;
    int eventPreRollFrames = 2;
    int eventPostRollFrames = 5;
    int eventAttackPostRollFrames = 10;
    std::string debugCsvDirectory;
};

class TimeStretchEngine {
public:
    explicit TimeStretchEngine(const StretchConfig& config);
    void reset();
    void setTimeRatio(double ratio);
    std::vector<std::vector<float>> processOffline(const std::vector<std::vector<float>>& input);
    double synthesisHop() const { return config_.analysisHop * config_.timeRatio; }
    std::size_t lastTransientCount() const { return lastTransientCount_; }
    std::size_t lastEventCount() const { return lastEventCount_; }
    const std::vector<TransientEvent>& lastEvents() const { return lastEvents_; }
    long long lastAnchorMaxErrorSamples() const { return lastAnchorMaxErrorSamples_; }
    std::size_t lastAnchoredEventCount() const { return lastAnchoredEventCount_; }
    const std::vector<TransientAnchor>& lastAnchors() const { return lastAnchors_; }
private:
    StretchConfig config_;
    STFT stft_;
    std::vector<PhaseVocoder> vocoders_;
    std::vector<float> frame_, synthesized_;
    std::vector<std::complex<float>> spectrum_, stretchedSpectrum_;
    std::size_t lastTransientCount_ = 0;
    std::size_t lastEventCount_ = 0;
    std::vector<TransientEvent> lastEvents_;
    long long lastAnchorMaxErrorSamples_ = 0;
    std::size_t lastAnchoredEventCount_ = 0;
    std::vector<TransientAnchor> lastAnchors_;
};
}
