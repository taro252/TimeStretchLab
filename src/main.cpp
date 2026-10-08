#include "audio/WavReader.h"
#include "audio/WavStream.h"
#include "audio/WavWriter.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

namespace {
void usage() {
    std::cerr << "Usage: timestretch input.wav output.wav --speed 0.5 "
                 "[--fft-size 4096] [--analysis-hop 1024] "
                 "[--phase-locking on|off] [--transient on|off] [--adaptive-time-map on|off] "
                 "[--selective-reset on|off] [--precise-anchoring on|off] [--stereo-coherence on|off] "
                 "[--coherence-strength 1] [--low-frequency-coherence 0.5] "
                 "[--multiresolution on|off] [--chunked on|off] [--chunk-size 16384] [--ablation a|b|c] [--debug-csv directory]\n"
                 "[--transient-sensitivity 3] [--transient-history 12] "
                 "[--transient-cooldown 2] [--transient-lookback 1] "
                 "[--event-distance 4] [--event-decay-merge 12] [--event-preroll 2] "
                 "[--event-postroll 5] [--attack-postroll 10]\n"
                 "Multiresolution uses FFT/hop 8192/2048, 4096/1024, 1024/256.\n";
}
double number(const char* text, const std::string& option) {
    std::size_t used = 0;
    const auto value = std::stod(text, &used);
    if (used != std::string(text).size() || !std::isfinite(value))
        throw std::invalid_argument("Invalid " + option);
    return value;
}
}
int main(int argc, char** argv) {
    if (argc < 4) { usage(); return 2; }
    try {
        double speed = -1;
        int fftSize = 4096, analysisHop = 1024;
        bool phaseLocking = false;
        bool transientHandling = false;
        bool adaptiveTimeMap = false;
        bool selectiveReset = false;
        bool preciseAnchoring = false;
        bool stereoCoherence = false;
        bool multiresolution = false;
        bool chunked = false;
        ts::AblationMode ablation = ts::AblationMode::Full;
        bool ablationSpecified = false;
        std::size_t chunkSize = 16384;
        float coherenceStrength = 1.0f, lowFrequencyCoherence = 0.5f;
        float transientSensitivity = 3.0f;
        int transientHistory = 12, transientCooldown = 2, transientLookback = 1;
        int eventDistance = 4, eventDecayMerge = 12, eventPreRoll = 2, eventPostRoll = 5;
        int attackPostRoll = 10;
        std::string debugCsvDirectory;
        bool hopSpecified = false;
        for (int i = 3; i < argc; i += 2) {
            if (i + 1 >= argc) throw std::invalid_argument("Option needs a value");
            const std::string key = argv[i], value = argv[i + 1];
            if (key == "--speed") speed = number(argv[i + 1], key);
            else if (key == "--fft-size") fftSize = static_cast<int>(number(argv[i + 1], key));
            else if (key == "--analysis-hop") {
                analysisHop = static_cast<int>(number(argv[i + 1], key)); hopSpecified = true;
            } else if (key == "--phase-locking") {
                if (value != "on" && value != "off") throw std::invalid_argument("--phase-locking expects on/off");
                phaseLocking = value == "on";
            } else if (key == "--transient") {
                if (value != "on" && value != "off") throw std::invalid_argument("--transient expects on/off");
                transientHandling = value == "on";
            } else if (key == "--adaptive-time-map") {
                if (value != "on" && value != "off") throw std::invalid_argument("--adaptive-time-map expects on/off");
                adaptiveTimeMap = value == "on";
            } else if (key == "--selective-reset") {
                if (value != "on" && value != "off") throw std::invalid_argument("--selective-reset expects on/off");
                selectiveReset = value == "on";
            } else if (key == "--precise-anchoring") {
                if (value != "on" && value != "off") throw std::invalid_argument("--precise-anchoring expects on/off");
                preciseAnchoring = value == "on";
            } else if (key == "--stereo-coherence") {
                if (value != "on" && value != "off") throw std::invalid_argument("--stereo-coherence expects on/off");
                stereoCoherence = value == "on";
            } else if (key == "--coherence-strength") {
                coherenceStrength = static_cast<float>(number(argv[i + 1], key));
            } else if (key == "--low-frequency-coherence") {
                lowFrequencyCoherence = static_cast<float>(number(argv[i + 1], key));
            } else if (key == "--transient-sensitivity") {
                transientSensitivity = static_cast<float>(number(argv[i + 1], key));
            } else if (key == "--transient-history") {
                transientHistory = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--transient-cooldown") {
                transientCooldown = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--transient-lookback") {
                transientLookback = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--event-distance") {
                eventDistance = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--event-decay-merge") {
                eventDecayMerge = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--event-preroll") {
                eventPreRoll = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--event-postroll") {
                eventPostRoll = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--attack-postroll") {
                attackPostRoll = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--debug-csv") {
                debugCsvDirectory = value;
            } else if (key == "--multiresolution") {
                if (value != "on" && value != "off") throw std::invalid_argument("--multiresolution expects on/off");
                multiresolution = value == "on";
            } else if (key == "--chunked") {
                if (value != "on" && value != "off") throw std::invalid_argument("--chunked expects on/off");
                chunked = value == "on";
            } else if (key == "--ablation") {
                ablationSpecified = true;
                if (value == "a") ablation = ts::AblationMode::MidOnly;
                else if (value == "b") ablation = ts::AblationMode::LowMid;
                else if (value == "c") ablation = ts::AblationMode::Full;
                else throw std::invalid_argument("--ablation expects a, b, or c");
            } else if (key == "--chunk-size") {
                const auto requested=number(argv[i+1],key);
                if (requested<8192 || requested>65536 || std::floor(requested)!=requested)
                    throw std::invalid_argument("--chunk-size expects 8192..65536 samples");
                chunkSize=static_cast<std::size_t>(requested);
            } else throw std::invalid_argument("Unknown/unsupported Phase 1 option: " + key);
        }
        if (!(speed > 0 && speed <= 1.25)) throw std::invalid_argument("Speed must be > 0 and <= 1.25");
        if (!hopSpecified) analysisHop = fftSize / 4;
        if (chunked && !multiresolution)
            throw std::invalid_argument("--chunked on requires --multiresolution on");
        if (ablationSpecified && !chunked)
            throw std::invalid_argument("--ablation requires --chunked on");
        if (chunked && !debugCsvDirectory.empty())
            throw std::invalid_argument("--debug-csv is unavailable with --chunked on");
        const ts::WavStreamReader metadata(argv[1]);
        ts::StretchConfig config;
        config.sampleRate = metadata.sampleRate();
        config.channels = static_cast<int>(metadata.channels());
        config.timeRatio = 1.0 / speed;
        config.fftSize = fftSize;
        config.analysisHop = analysisHop;
        config.enablePhaseLocking = phaseLocking;
        config.enableTransientHandling = transientHandling;
        config.enableAdaptiveTimeMapping = adaptiveTimeMap;
        config.enableSelectivePhaseReset = selectiveReset;
        config.enablePreciseTransientAnchoring = preciseAnchoring;
        config.enableStereoCoherence = stereoCoherence;
        config.stereoCoherenceStrength = coherenceStrength;
        config.lowFrequencyCoherenceStrength = lowFrequencyCoherence;
        config.enableMultiResolution = multiresolution;
        config.transientSensitivity = transientSensitivity;
        config.transientHistoryFrames = transientHistory;
        config.transientCooldownFrames = transientCooldown;
        config.transientLookbackFrames = transientLookback;
        config.eventMinimumDistanceFrames = eventDistance;
        config.eventDecayMergeFrames = eventDecayMerge;
        config.eventPreRollFrames = eventPreRoll;
        config.eventPostRollFrames = eventPostRoll;
        config.eventAttackPostRollFrames = attackPostRoll;
        config.debugCsvDirectory = debugCsvDirectory;
        if (chunked) {
            ts::ChunkedTimeStretchEngine engine(config);
            const auto start=std::chrono::steady_clock::now();
            const auto result=engine.processWav(argv[1],argv[2],chunkSize,ablation);
            const auto elapsed=std::chrono::duration<double>(
                std::chrono::steady_clock::now()-start).count();
            rusage usage{};
            const auto resourceMeasured=getrusage(RUSAGE_SELF,&usage)==0;
            const auto memoryBytes=resourceMeasured
                ? static_cast<long long>(usage.ru_maxrss) : -1LL;
            const auto cpuSeconds=resourceMeasured
                ? double(usage.ru_utime.tv_sec)+usage.ru_utime.tv_usec/1e6+
                  double(usage.ru_stime.tv_sec)+usage.ru_stime.tv_usec/1e6 : -1.0;
            std::cout << "FFT=" << fftSize << " Ha=" << analysisHop
                      << " speed=" << speed << " phase_locking=" << (phaseLocking?"on":"off")
                      << " transient=" << (transientHandling?"on":"off")
                      << " transient_count=" << result.transientCount
                      << " adaptive_time_map=" << (adaptiveTimeMap?"on":"off")
                      << " precise_anchoring=" << (preciseAnchoring?"on":"off")
                      << " stereo_coherence=" << (stereoCoherence?"on":"off")
                      << " average_coherence_weight=" << result.averageCoherenceWeight
                      << " multiresolution=on chunked=on chunk_size=" << result.chunkSize
                      << " ablation=" << (ablation==ts::AblationMode::MidOnly?"a":
                            ablation==ts::AblationMode::LowMid?"b":"c")
                      << " ola_ring_samples=" << result.olaRingSamples
                      << " fir_ring_samples=" << result.firRingSamples
                      << " event_count=" << result.eventCount
                      << " time_map_hash=" << result.timeMapHash
                      << " anchored_event_count=" << result.anchoredEventCount
                      << " max_event_anchor_error_samples=" << result.maxAnchorErrorSamples
                      << " input_frames=" << result.inputFrames
                      << " output_frames=" << result.outputFrames
                      << " processing_seconds=" << elapsed << " peak=" << result.peak
                      << " cpu_seconds=" << cpuSeconds
                      << " max_rss_bytes=" << memoryBytes << '\n';
            return 0;
        }
        const auto input = ts::WavReader::read(argv[1]);
        ts::TimeStretchEngine engine(config);
        const auto start = std::chrono::steady_clock::now();
        const auto output = engine.processOffline(input.channels);
        std::uint64_t timeMapHash=14695981039346656037ULL;
        for (const auto position: engine.lastTimeMap().starts()) {
            timeMapHash^=static_cast<std::uint64_t>(position);
            timeMapHash*=1099511628211ULL;
        }
        const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        rusage usage{};
        const auto memoryBytes = getrusage(RUSAGE_SELF, &usage) == 0
            ? static_cast<long long>(usage.ru_maxrss) : -1LL;
        ts::WavWriter::write(argv[2], {input.sampleRate, output});
        float peak = 0;
        for (const auto& channel : output) for (float sample : channel)
            peak = std::max(peak, std::abs(sample));
        std::size_t gapUnder50 = 0, gapUnder100 = 0, gapUnder200 = 0, gapAtLeast200 = 0;
        const auto& events = engine.lastEvents();
        for (std::size_t i = 1; i < events.size(); ++i) {
            const double gapMs = 1000.0 * (events[i].peakFrame - events[i - 1].peakFrame)
                * analysisHop / input.sampleRate;
            if (gapMs < 50) ++gapUnder50;
            else if (gapMs < 100) ++gapUnder100;
            else if (gapMs < 200) ++gapUnder200;
            else ++gapAtLeast200;
        }
        std::cout << "FFT=" << fftSize << " Ha=" << analysisHop
                  << " Hs=" << engine.synthesisHop() << " speed=" << speed
                  << " phase_locking=" << (phaseLocking ? "on" : "off")
                  << " transient=" << (transientHandling ? "on" : "off")
                  << " transient_count=" << engine.lastTransientCount()
                  << " adaptive_time_map=" << (adaptiveTimeMap ? "on" : "off")
                  << " selective_reset=" << (selectiveReset ? "on" : "off")
                  << " precise_anchoring=" << (preciseAnchoring ? "on" : "off")
                  << " stereo_coherence=" << (stereoCoherence ? "on" : "off")
                  << " average_coherence_weight=" << engine.lastAverageCoherenceWeight()
                  << " multiresolution=" << (multiresolution ? "on" : "off")
                  << " resolution_fft_hops=" << (multiresolution
                        ? "8192/2048,4096/1024,1024/256" : "single")
                  << " crossover_working_bytes=" << engine.lastCrossoverWorkingMemoryBytes()
                  << " anchored_event_count=" << engine.lastAnchoredEventCount()
                  << " event_count=" << engine.lastEventCount()
                  << " time_map_hash=" << timeMapHash
                  << " events_per_second=" << (input.channels.front().empty() ? 0.0 :
                        engine.lastEventCount() * input.sampleRate /
                        double(input.channels.front().size()))
                  << " gaps_lt50ms=" << gapUnder50
                  << " gaps_50to100ms=" << gapUnder100
                  << " gaps_100to200ms=" << gapUnder200
                  << " gaps_ge200ms=" << gapAtLeast200
                  << " max_event_anchor_error_samples=" << engine.lastAnchorMaxErrorSamples()
                  << " input_frames=" << input.channels.front().size()
                  << " output_frames=" << output.front().size()
                  << " processing_seconds=" << elapsed << " peak=" << peak
                  << " max_rss_bytes=" << memoryBytes << '\n';
        if (peak > 1.0f) std::cerr << "Warning: output peak exceeds 1.0 (no normalization applied)\n";
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n'; usage(); return 1;
    }
}
