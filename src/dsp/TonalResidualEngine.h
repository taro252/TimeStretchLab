#pragma once
#include "dsp/SinusoidalResidualEngine.h"
#include <filesystem>
#include <vector>

namespace ts {
struct TonalResidualResult {
    std::vector<float> output;
    std::vector<float> primary;
    std::vector<float> tonalInput,noiseInput;
    std::vector<float> tonalOutput,noiseOutput,primaryAndTonal;
    SinusoidalResidualStats primaryStats;
    double meanTonalMask=0;
};

// Independent Phase 9C experiment. Phase 9A and Phase 5.3 are unchanged.
class TonalResidualEngine {
public:
    explicit TonalResidualEngine(SinusoidalResidualConfig config);
    TonalResidualResult processMono(const std::vector<float>& input,
        const std::filesystem::path& trackCsv={});
private:
    SinusoidalResidualConfig config_;
};
}
