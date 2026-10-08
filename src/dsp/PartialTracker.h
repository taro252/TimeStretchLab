#pragma once
#include "dsp/PhaseLocker.h"
#include <array>
#include <complex>
#include <cstddef>
#include <vector>

namespace ts {
class PhaseVocoder;

struct TrackChannelState {
    double previousAnalysisPhase = 0;
    double synthesisPhase = 0;
    double angularFrequency = 0;
    bool valid = false;
};

struct TrackedPeak {
    int trackId = -1;
    int bin = 0;
    float interpolatedBin = 0;
    float magnitude = 0;
    float frequencyHz = 0;
    int age = 0;
    int missedFrames = 0;
    double pendingSynthesisHop = 0;
    bool active = false;
    bool matched = false;
    std::array<TrackChannelState,2> channel;
};

struct PartialTrackingStats {
    std::size_t trackablePeakFrames = 0;
    std::size_t matchedPeakFrames = 0;
    std::size_t appliedPeakFrames = 0;
    std::size_t births = 0;
    std::size_t trackSwitches = 0;
    std::size_t processedFrames = 0;
    std::size_t activeTrackFrames = 0;
    double finishedLifetimeFrames = 0;
    std::size_t finishedTracks = 0;
    double phaseDiscontinuitySum = 0;
    double phaseDiscontinuityMax = 0;
    std::size_t phaseDiscontinuityCount = 0;
};

// One shared peak identity map; each channel keeps its own phase accumulator.
// The pool, owner map, and matching workspace are allocated at construction.
class PartialTracker {
public:
    PartialTracker(std::size_t fftSize,int analysisHop,double sampleRate,int channels);
    void reset(bool countLifetimes = true);
    void process(const PhaseLocker& peaks,
                 const std::array<const std::complex<float>*,2>& input,
                 const std::array<std::complex<float>*,2>& output,
                 const std::array<PhaseVocoder*,2>& vocoders,
                 double synthesisHop,bool resetPhase);
    void synchronize(const std::array<std::complex<float>*,2>& output);
    int trackIdForBin(std::size_t bin) const;
    const PartialTrackingStats& stats() const { return stats_; }
    double averageLifetimeFrames() const;
    double averageTrackCount() const;
    double continuityRatio() const;
private:
    std::size_t fftSize_, binCount_;
    int analysisHop_, channels_, nextId_ = 0;
    double sampleRate_;
    std::vector<TrackedPeak> tracks_;
    std::vector<int> trackForPeakBin_;
    std::vector<int> activeIndices_;
    std::vector<int> previousPeakIds_, currentPeakIds_;
    PartialTrackingStats stats_;
    bool eligible(const SpectralPeak& peak,const PhaseLocker& map,float frameMax) const;
    int findMatch(float frequencyHz,float magnitude) const;
    int acquireSlot();
};
}
