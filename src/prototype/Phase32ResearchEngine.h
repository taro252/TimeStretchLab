#pragma once
#include "dsp/ChunkedTimeStretchEngine.h"

namespace ts {
// Isolated Phase 32 diagnostics. None of these options affect the frozen DSP.
struct Phase32Options {
    bool resetOnTransient = true;
    bool resetEveryFrame = false;
    bool writeResolutionStems = false;
};
class Phase32ResearchEngine {
public:
    explicit Phase32ResearchEngine(StretchConfig config, Phase32Options options = {});
    ChunkedResult processWav(const std::filesystem::path& input,
                             const std::filesystem::path& output,
                             std::size_t chunkSize=16384);
private:
    StretchConfig config_;
    Phase32Options options_;
};
}
