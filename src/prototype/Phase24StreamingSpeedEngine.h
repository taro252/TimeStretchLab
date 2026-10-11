#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <filesystem>
#include <functional>

namespace ts::prototype {

// Worker-owned mutable timeline. The hook runs after a complete PCM block has
// been published, before synthesis of the next block starts.
class Phase24StreamingSpeedEngine {
public:
    using OutputSink=Phase13StreamingEngine::OutputSink;
    using UpdateHook=std::function<void(std::size_t publishedFrames,
        std::size_t firstUnprocessedInputSample,TimeMap& map,
        std::size_t& outputFrames)>;
    explicit Phase24StreamingSpeedEngine(StretchConfig config);
    Phase13Result process(const std::filesystem::path& input,
                          const Phase13TransientAnalysis& analysis,
                          TimeMap map,std::size_t outputFrames,
                          const OutputSink& sink,const UpdateHook& update,
                          std::size_t blockFrames=8192);
private:
    StretchConfig config_;
};
}
