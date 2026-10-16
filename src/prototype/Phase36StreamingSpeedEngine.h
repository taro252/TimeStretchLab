#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <array>
#include <filesystem>
#include <functional>
#include <iosfwd>
#include <vector>
#include <chrono>
#include <cstdint>

namespace ts::prototype {

// Research-only incremental counterpart of Phase 35. The worker owns this
// engine and may update the map only at a frontier reported by its hook.
class Phase36StreamingSpeedEngine {
public:
    struct StageTime { double wallSeconds=0,threadCpuSeconds=0; };
    struct WorkProfile {
        // Worker-local, reset at each output block; no callback-thread access.
        std::array<StageTime,5> stages{}; // WAV read, FFT, phase, IFFT/OLA, FIR
        struct PhaseFrames {
            std::size_t frames=0,sharedPeaks=0,maxSharedPeaks=0,resets=0;
            std::size_t firstInput=0,lastInput=0,neighborhoodEvaluations=0;
        };
        std::array<PhaseFrames,3> phaseFrames{};
        // Optional bounded experimental observer. No ownership or allocation.
        using Observer=void(*)(void*,std::size_t,std::size_t,bool,std::uint64_t,double) noexcept;
        Observer observer=nullptr;
        void* observerContext=nullptr;
    };
    struct Frontier {
        static constexpr std::size_t historySize=24;
        std::size_t preparedOutput=0;
        std::array<std::size_t,3> nextInput{};
        std::array<std::size_t,3> lastProcessedInput{};
        std::array<std::size_t,3> finalizedOla{};
        std::array<std::size_t,2> firstUnprocessedFirSource{};
        // Read-only research telemetry. Old code paths leave counts at zero.
        std::array<std::array<std::size_t,historySize>,3> recentFrameInput{};
        std::array<std::array<long long,historySize>,3> recentFrameOutput{};
        std::array<std::size_t,3> recentFrameCount{};
        std::array<std::size_t,3> actualWeightSample{};
        std::array<float,3> actualWeight{};
    };
    using PreparedSink=std::function<void(const float* const*,std::size_t,
        const std::function<void()>& poll)>;
    using UpdateHook=std::function<void(const Frontier&,TimeMap&,std::size_t&,
        std::vector<std::pair<std::size_t,bool>>&)>;
    using ProfileHook=std::function<void(std::size_t,const WorkProfile&)>;
    explicit Phase36StreamingSpeedEngine(StretchConfig config);
    Phase13Result process(const std::filesystem::path& input,
        const Phase13TransientAnalysis& analysis,TimeMap map,
        std::size_t outputFrames,std::size_t blockFrames,
        const PreparedSink& sink,const UpdateHook& update,
        std::vector<std::pair<std::size_t,bool>> modeChanges={},
        const ProfileHook& profileHook={},std::ostream* componentCsv=nullptr,
        std::size_t probeFirst=0,std::size_t probeLast=0,
        bool recordFrameHistory=false,const std::function<void()>& initialized={});
private:
    StretchConfig config_;
};
}
