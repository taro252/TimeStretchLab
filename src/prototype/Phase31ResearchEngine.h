#pragma once
#include "dsp/ChunkedTimeStretchEngine.h"

namespace ts {
// Isolated Phase 31 experiment. The original offline/streaming DSP is frozen.
// Only analysis frame spacing below 0.50x differs from Experimental 3500.
class Phase31ResearchEngine {
public:
    explicit Phase31ResearchEngine(StretchConfig config);
    ChunkedResult processWav(const std::filesystem::path& input,
                             const std::filesystem::path& output,
                             std::size_t chunkSize=16384);
private:
    StretchConfig config_;
};
}
