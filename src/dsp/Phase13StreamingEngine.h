#pragma once

#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/TransientAnchor.h"
#include <array>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>

namespace ts {

struct Phase13TransientData;

// Input-domain snapshot. Event grouping and sample-level anchors can be reused
// when building separate fixed-speed output timelines for the same known file.
class Phase13TransientAnalysis {
public:
    std::size_t inputFrames() const;
    std::size_t transientCount() const;
    const std::vector<TransientEvent>& events() const;
    const std::vector<TransientAnchor>& anchors() const;
    const std::vector<TransientFrame>& detectorFrames() const;
    std::size_t activeFrameCount() const;
private:
    std::shared_ptr<const Phase13TransientData> impl_;
    friend class Phase13StreamingEngine;
};

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

// Immutable fixed-speed preparation for one known file.
// The DSP worker may read it after the analysis thread has completed.
class Phase13PreparedFile {
public:
    Phase13PreparedFile() = default;
    std::size_t inputFrames() const;
    std::size_t outputFrames() const;
    // Frozen pre-analysis map. The output sample is the first sample selected
    // when a UI request names an input sample; output-frame seek remains exact.
    std::size_t outputFrameForInputFrame(std::size_t inputFrame) const;
private:
    struct Impl;
    std::shared_ptr<const Impl> impl_;
    friend class Phase13StreamingEngine;
};

// Known-file, fixed-speed prototype. Pre-analysis finishes before the first
// callback. The callback consumes planar samples immediately; no full output
// buffer or WAV writer is owned by this DSP class.
class Phase13StreamingEngine {
public:
    using OutputSink = std::function<void(const float* const*, std::size_t)>;
    explicit Phase13StreamingEngine(StretchConfig config);
    Phase13TransientAnalysis analyzeTransientEvents(const std::filesystem::path& input) const;
    Phase13PreparedFile prepareWithAnalysis(const Phase13TransientAnalysis& analysis) const;
    Phase13PreparedFile analyzeFile(const std::filesystem::path& input) const;
    Phase13Result processPrepared(const Phase13PreparedFile& prepared,
                                  const OutputSink& sink,
                                  std::size_t outputBlockFrames = 16384);
    Phase13Result processFile(const std::filesystem::path& input,
                              const OutputSink& sink,
                              std::size_t outputBlockFrames = 16384);
private:
    StretchConfig config_;
};
}
