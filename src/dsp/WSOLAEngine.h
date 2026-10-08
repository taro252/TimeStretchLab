#pragma once
#include <cstddef>
#include <filesystem>
#include <vector>

namespace ts {
struct WSOLAConfig {
    double sampleRate=48000;
    double timeRatio=2.0;
    std::size_t windowSize=2048;
    std::size_t synthesisHop=512;
    int searchRadius=512;
};
struct WSOLAGrain {
    std::size_t grainIndex=0;
    double expectedAnalysisSample=0;
    long long selectedAnalysisSample=0;
    int offsetSamples=0;
    double maxCorrelation=0;
    std::size_t outputSample=0;
    bool searched=false;
};
struct WSOLAStats {
    std::size_t grainCount=0;
    double averageAbsoluteOffset=0;
    double p95AbsoluteOffset=0;
    double averageCorrelation=0;
    double p10Correlation=0;
};

// Independent time-domain overlap/add engine. Its grain scheduler and
// correlation state can later be paired with ring-buffer output storage.
class WSOLAEngine {
public:
    explicit WSOLAEngine(WSOLAConfig config);
    std::vector<std::vector<float>> processOffline(
        const std::vector<std::vector<float>>& input,
        const std::filesystem::path& diagnosticsCsv={});
    const WSOLAConfig& config() const { return config_; }
    const std::vector<WSOLAGrain>& grains() const { return grains_; }
    WSOLAStats stats() const;
private:
    double inputMid(const std::vector<std::vector<float>>& input,long long sample) const;
    double outputMid(const std::vector<std::vector<float>>& sums,
                     const std::vector<float>& weights,std::size_t sample) const;
    double correlation(const std::vector<std::vector<float>>& input,
                       const std::vector<std::vector<float>>& sums,
                       const std::vector<float>& weights,long long outputStart,
                       long long candidateInputStart) const;
    WSOLAConfig config_;
    std::vector<float> window_;
    std::vector<WSOLAGrain> grains_;
};
}
