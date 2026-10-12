#pragma once
#include "dsp/ChunkedTimeStretchEngine.h"

namespace ts {
// Offline-only trace copy of the Phase 32 research renderer.
struct Phase33TraceOptions {
    bool resetOnTransient = true;
    bool resetEveryFrame = false;
    bool writeResolutionStems = false;
    std::filesystem::path traceDirectory;
};
class Phase33TraceEngine {
public:
    explicit Phase33TraceEngine(StretchConfig config, Phase33TraceOptions options = {});
    ChunkedResult processWav(const std::filesystem::path& input,
                             const std::filesystem::path& output,
                             std::size_t chunkSize=16384);
private:
    StretchConfig config_;
    Phase33TraceOptions options_;
};
}
