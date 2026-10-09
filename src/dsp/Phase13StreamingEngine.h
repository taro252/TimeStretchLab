#pragma once

#include "dsp/ChunkedTimeStretchEngine.h"
#include <array>
#include <cstdint>
#include <filesystem>
#include <functional>

namespace ts {

// Diagnostic digests are accumulated in frame/sample order, independent of
// the output callback's block size. Index order: Low, Mid, High.
struct Phase13StageDigests {
    std::array<std::uint64_t,3> fft{};
    std::array<std::uint64_t,3> phase{};
    std::array<std::uint64_t,3> ifft{};
    std::array<std::uint64_t,3> ola{};
    std::uint64_t lowFir = 0;
    std::uint64_t highFir = 0;
    std::uint64_t fir = 0;
};

struct Phase13Result {
    ChunkedResult processing;
    Phase13StageDigests stages;
};

// Known-file, fixed-speed prototype. Pre-analysis finishes before the first
// callback. The callback consumes planar samples immediately; no full output
// buffer or WAV writer is owned by this DSP class.
class Phase13StreamingEngine {
public:
    using OutputSink = std::function<void(const float* const*, std::size_t)>;
    explicit Phase13StreamingEngine(StretchConfig config);
    Phase13Result processFile(const std::filesystem::path& input,
                              const OutputSink& sink,
                              std::size_t outputBlockFrames = 16384);
private:
    StretchConfig config_;
};
}
