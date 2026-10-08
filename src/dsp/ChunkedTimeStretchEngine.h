#pragma once
#include "dsp/TimeStretchEngine.h"
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>

namespace ts {
enum class AblationMode { MidOnly, LowMid, Full };
struct ChunkedResult {
    std::size_t inputFrames = 0, outputFrames = 0;
    std::size_t transientCount = 0, eventCount = 0, anchoredEventCount = 0;
    long long maxAnchorErrorSamples = 0;
    double averageCoherenceWeight = 0;
    float peak = 0;
    std::size_t chunkSize = 0, olaRingSamples = 0, firRingSamples = 0;
    std::uint64_t timeMapHash = 0;
    std::size_t trackablePeakFrames = 0, matchedPeakFrames = 0;
    std::size_t appliedPeakFrames = 0, trackSwitches = 0;
    double averageTrackLifetimeFrames = 0, averageTrackCount = 0;
    double peakPhaseDiscontinuityMean = 0, peakPhaseDiscontinuityMax = 0;
    std::size_t resyncScheduled=0,resyncApplied=0,resyncTransientSuppressed=0;
    double averageResyncCorrelation=0,averageResyncOffsetSamples=0;
};

class ChunkedTimeStretchEngine {
public:
    explicit ChunkedTimeStretchEngine(StretchConfig config);
    ChunkedResult processWav(const std::filesystem::path& input,
                             const std::filesystem::path& output,
                             std::size_t chunkSize = 16384,
                             std::optional<AblationMode> mode = std::nullopt);
private:
    StretchConfig config_;
};
}
