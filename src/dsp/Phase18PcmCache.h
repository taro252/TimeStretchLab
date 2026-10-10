#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <optional>
#include <string>
#include <thread>

namespace ts {

// Control/worker-thread cache for frozen Experimental3500 0.50x output.
// Never accessed from an audio render callback.
class Phase18PcmCache {
public:
    Phase18PcmCache(std::filesystem::path source,std::filesystem::path directory,
                    StretchConfig config);
    ~Phase18PcmCache();
    Phase18PcmCache(const Phase18PcmCache&)=delete;
    Phase18PcmCache& operator=(const Phase18PcmCache&)=delete;

    std::optional<std::filesystem::path> validPath(double* validationSeconds=nullptr) const;
    void beginGeneration();
    void wait();
    bool generationFinished() const noexcept { return finished_.load(std::memory_order_acquire); }
    double generationSeconds() const noexcept { return generationSeconds_.load(); }
    std::string generationError() const;
    const std::string& key() const noexcept { return key_; }
    std::filesystem::path cachePath() const { return dataPath_; }
    std::size_t outputFrames() const noexcept { return frames_; }
private:
    void generate();
    std::filesystem::path source_,directory_,dataPath_,metadataPath_;
    StretchConfig config_;
    std::string inputHash_,key_,environment_;
    std::uint32_t rate_=0;
    std::size_t channels_=0,frames_=0;
    std::thread worker_;
    std::atomic<bool> finished_{true};
    std::atomic<double> generationSeconds_{0};
    std::string error_;
};
}
