#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "playback/StartupDiagnostics.h"
#include <memory>
#include <mutex>
#include <condition_variable>
#include <vector>
#include <string>
namespace ts::playback {
class PinnedInput;
struct SharedInputAnalysis {
    Phase13TransientAnalysis analysis;
    // Keeps the analysis snapshot's descriptor pathname valid as well.
    std::shared_ptr<const PinnedInput> origin;
    std::string contentSha256,version;
    std::size_t bytes=0;
};
struct AnalysisLease {
    std::shared_ptr<const SharedInputAnalysis> data;
    std::shared_ptr<const PinnedInput> input;
    std::filesystem::path path()const;
    void validate()const; // Worker/control only; never audio callback.
};
struct AnalysisCacheDiagnostics {std::size_t residentBytes=0,limitBytes=0,entries=0,maxEntries=64;std::uint64_t analyses=0,hits=0,sharedFlights=0,bytesHashed=0,evictions=0;};
// Memory-only, immutable input-domain data. Thread-safe; capacity 0 disables retention.
class PlaybackAnalysisCache {
public:
    explicit PlaybackAnalysisCache(std::size_t capacityBytes=32*1024*1024,std::size_t maxEntries=64);
    AnalysisLease acquire(const std::filesystem::path&,StartupDiagnostics&);
    void setCapacity(std::size_t);AnalysisCacheDiagnostics diagnostics()const;
    static std::shared_ptr<PlaybackAnalysisCache> sharedDefault();
private:
    struct Entry;
    void evictLocked(std::size_t reservation=0,std::size_t entries=0);
    mutable std::mutex mutex_;
    std::vector<std::shared_ptr<Entry>> entries_;
    AnalysisCacheDiagnostics stats_;std::uint64_t clock_=0;
};
}
