#pragma once
#include "audio/WavStream.h"
#include "dsp/PhaseLocker.h"
#include "dsp/RingOverlapAdd.h"
#include "dsp/TimeStretchEngine.h"
#include <cstddef>
#include <vector>

namespace ts {
struct ResyncDecision {
    bool scheduled=false,applied=false,transientSuppressed=false;
    int offsetSamples=0;
    double correlation=0,tonality=0;
};
struct ResyncStats {
    std::size_t scheduled=0,applied=0,transientSuppressed=0;
    double correlationSum=0,absoluteOffsetSum=0;
};

// A small waveform search around the Mid analysis frame. Search coordinates
// change only the phase-reference frame; output placement stays on TimeMap.
class PeriodicResynchronizer {
public:
    PeriodicResynchronizer(const StretchConfig& config,std::size_t fftSize,int hop);
    ResyncDecision consider(std::size_t frame,long long outputStart,
                            long long inputStart,const std::vector<bool>& resets,
                            const PhaseLocker& peaks,WavStreamReader& reader,
                            const std::vector<RingOverlapAdd>& olas);
    const ResyncStats& stats() const { return stats_; }
    double intervalMs() const { return intervalMs_; }
    int rangeSamples() const { return rangeSamples_; }
private:
    double tonality(const PhaseLocker& peaks) const;
    double correlation(int offset,long long outputStart,long long inputStart,
                       WavStreamReader& reader,const std::vector<RingOverlapAdd>& olas) const;
    double sampleInput(WavStreamReader& reader,long long sample) const;
    double sampleOutput(const std::vector<RingOverlapAdd>& olas,long long sample) const;
    double sampleRate_,intervalMs_,threshold_;
    int intervalFrames_,rangeSamples_,fftSize_;
    std::size_t lastAppliedFrame_=0;
    bool hasApplied_=false;
    ResyncStats stats_;
};
}
