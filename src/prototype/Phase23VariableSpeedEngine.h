#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <filesystem>
#include <ostream>

namespace ts::prototype {

// Independent known-file WAV generator. It takes an already finalized common
// TimeMap; no speed state or DSP component is reset at its change point.
class Phase23VariableSpeedEngine {
public:
    using OutputSink=Phase13StreamingEngine::OutputSink;
    explicit Phase23VariableSpeedEngine(StretchConfig config);
    Phase13Result process(const std::filesystem::path& input,
                          const Phase13TransientAnalysis& analysis,
                          const TimeMap& map,std::size_t outputFrames,
                          const OutputSink& sink,std::size_t blockFrames=16384,
                          std::ostream* stageTrace=nullptr,
                          std::size_t probeInputSample=0);
private:
    StretchConfig config_;
};
}
