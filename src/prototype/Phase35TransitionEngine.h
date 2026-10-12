#pragma once
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/TimeMap.h"
#include <ostream>

namespace ts {
// Isolated variable-analysis-hop prototype; frozen production DSP is untouched.
class Phase35TransitionEngine {
public:
    explicit Phase35TransitionEngine(StretchConfig config);
    ChunkedResult processWav(const std::filesystem::path& input,
                             const std::filesystem::path& output,
                             const TimeMap& map, const std::vector<std::pair<std::size_t,bool>>& modeChanges,
                             std::size_t outputFrames, std::size_t chunkSize=16384,
                             std::ostream* frameTrace=nullptr);
private:
    StretchConfig config_;
};
}
