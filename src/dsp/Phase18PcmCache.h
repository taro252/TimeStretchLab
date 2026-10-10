#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>
#include <array>

namespace ts {

struct Phase19CachePolicy {
    std::uint64_t maximumBytes=2ULL*1024*1024*1024;
    double freeSpaceFraction=0.10;
};

// An opened, verified snapshot. The descriptor and shared key lock remain live
// through every seek/worker read, even if the pathname is replaced or removed.
class VerifiedPcmCache {
public:
    ~VerifiedPcmCache();
    VerifiedPcmCache(const VerifiedPcmCache&)=delete;
    VerifiedPcmCache& operator=(const VerifiedPcmCache&)=delete;
    std::size_t frames() const noexcept { return frames_; }
    std::size_t channels() const noexcept { return channels_; }
    std::uint32_t sampleRate() const noexcept { return rate_; }
    // Worker only. Checks each 4096-frame block against its initial digest
    // before exposing any samples to the FIFO.
    void readFrames(std::size_t first,std::size_t count,float* const* output) const;
private:
    friend class Phase18PcmCache;
    VerifiedPcmCache(int dataFd,int lockFd,std::size_t frames,std::size_t channels,
                     std::uint32_t rate,std::vector<std::array<unsigned char,32>> hashes);
    int dataFd_=-1,lockFd_=-1;
    std::size_t frames_=0,channels_=0;
    std::uint32_t rate_=0;
    std::vector<std::array<unsigned char,32>> hashes_;
};

// Control/worker-thread cache for frozen Experimental3500 0.50x output.
// Never accessed from an audio render callback.
class Phase18PcmCache {
public:
    Phase18PcmCache(std::filesystem::path source,std::filesystem::path directory,
                    StretchConfig config,Phase19CachePolicy policy={});
    ~Phase18PcmCache();
    Phase18PcmCache(const Phase18PcmCache&)=delete;
    Phase18PcmCache& operator=(const Phase18PcmCache&)=delete;

    std::optional<std::filesystem::path> validPath(double* validationSeconds=nullptr) const;
    std::shared_ptr<const VerifiedPcmCache> acquireVerified(double* validationSeconds=nullptr);
    void invalidateSession() noexcept { verified_.reset(); }
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
    void checkInputIdentity() const;
    bool ensureCapacity(std::uint64_t neededBytes);
    void cleanupOrphans();
    std::filesystem::path source_,directory_,dataPath_,metadataPath_;
    StretchConfig config_;
    Phase19CachePolicy policy_;
    std::string inputHash_,key_,environment_;
    std::uint32_t rate_=0;
    std::size_t channels_=0,frames_=0;
    int sourceFd_=-1;
    std::uint64_t sourceDev_=0,sourceIno_=0,sourceSize_=0;
    std::int64_t sourceMtimeSec_=0,sourceMtimeNsec_=0,sourceCtimeSec_=0,sourceCtimeNsec_=0;
    std::shared_ptr<const VerifiedPcmCache> verified_;
    std::thread worker_;
    std::atomic<bool> finished_{true};
    std::atomic<double> generationSeconds_{0};
    std::string error_;
};
}
