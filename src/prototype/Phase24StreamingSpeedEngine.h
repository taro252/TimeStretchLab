#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <filesystem>
#include <functional>
#include <array>

namespace ts::prototype {

// Worker-owned mutable timeline. The hook runs after a complete PCM block has
// been published, before synthesis of the next block starts.
class Phase24StreamingSpeedEngine {
public:
    using OutputSink=Phase13StreamingEngine::OutputSink;
    using UpdateHook=std::function<void(std::size_t publishedFrames,
        std::size_t firstUnprocessedInputSample,TimeMap& map,
        std::size_t& outputFrames)>;
    // Phase 25: a prepared block is immutable. The worker may poll the map
    // while waiting to publish it, protecting the entire prepared block.
    using PreparedSink=std::function<void(const float* const*,std::size_t,
        const std::function<void()>& poll)>;
    struct ProcessingFrontier {
        std::size_t preparedOutput=0;
        // Next STFT frame per resolution; every preceding frame already
        // updated phase and OLA state and must retain its TimeMap coordinate.
        std::array<std::size_t,3> firstUnprocessedInput{};
        // First source sample not yet transformed by each crossover FIR.
        std::array<std::size_t,2> firstUnprocessedFirSource{};
    };
    using DetailedUpdateHook=std::function<void(const ProcessingFrontier&,
        TimeMap& map,std::size_t& outputFrames)>;
    explicit Phase24StreamingSpeedEngine(StretchConfig config);
    Phase13Result process(const std::filesystem::path& input,
                          const Phase13TransientAnalysis& analysis,
                          TimeMap map,std::size_t outputFrames,
                          const OutputSink& sink,const UpdateHook& update,
                          std::size_t blockFrames=8192,
                          const PreparedSink& preparedSink={},
                          const DetailedUpdateHook& detailedUpdate={});
private:
    StretchConfig config_;
};
}
