#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <array>
#include <filesystem>
#include <functional>
#include <vector>

namespace ts::prototype {

// Research-only incremental counterpart of Phase 35. The worker owns this
// engine and may update the map only at a frontier reported by its hook.
class Phase36StreamingSpeedEngine {
public:
    struct Frontier {
        std::size_t preparedOutput=0;
        std::array<std::size_t,3> nextInput{};
        std::array<std::size_t,3> lastProcessedInput{};
        std::array<std::size_t,3> finalizedOla{};
        std::array<std::size_t,2> firstUnprocessedFirSource{};
    };
    using PreparedSink=std::function<void(const float* const*,std::size_t,
        const std::function<void()>& poll)>;
    using UpdateHook=std::function<void(const Frontier&,TimeMap&,std::size_t&,
        std::vector<std::pair<std::size_t,bool>>&)>;
    explicit Phase36StreamingSpeedEngine(StretchConfig config);
    Phase13Result process(const std::filesystem::path& input,
        const Phase13TransientAnalysis& analysis,TimeMap map,
        std::size_t outputFrames,std::size_t blockFrames,
        const PreparedSink& sink,const UpdateHook& update,
        std::vector<std::pair<std::size_t,bool>> modeChanges={});
private:
    StretchConfig config_;
};
}
