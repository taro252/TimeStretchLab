#include "prototype/Phase37HighSpeedMap.h"
#include "audio/WavStream.h"
#include "dsp/TransientEventMap.h"
#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "Usage: phase38_events input.wav speed A|B\n";
        return 2;
    }
    try {
        const auto speed = std::stod(argv[2]);
        const std::string mode = argv[3];
        if (!std::isfinite(speed) || speed < 1 || speed > 2 ||
            (mode != "A" && mode != "B"))
            throw std::invalid_argument("Invalid speed or mode");
        ts::WavStreamReader source(argv[1]);
        ts::StretchConfig config;
        config.sampleRate = source.sampleRate();
        config.channels = source.channels();
        config.timeRatio = 1;
        config.enableMultiResolution = true;
        config.qualityMode = ts::QualityMode::Experimental;
        config.enablePhaseLocking = true;
        config.enableTransientHandling = true;
        config.enableAdaptiveTimeMapping = true;
        config.enablePreciseTransientAnchoring = true;
        config.enableStereoCoherence = true;
        ts::Phase13StreamingEngine analyzer(config);
        const auto analysis = analyzer.analyzeTransientEvents(argv[1]);
        const auto ratio = 1 / speed;
        ts::prototype::Phase37MapDiagnostics diagnostics;
        const auto map = ts::prototype::phase37Map(
            analysis, source.frames(), ratio, mode == "B", &diagnostics);
        ts::TransientEventMap frozen(analysis.detectorFrames(),
            analysis.activeFrameCount(), 1024, ratio, {}, analysis.events());
        std::vector<double> offsets;
        for (const auto& anchor : analysis.anchors())
            offsets.push_back(anchor.sampleOffset);
        if (!offsets.empty()) frozen.refineAnchors(offsets);
        std::cout << "event,onset_frame,peak_frame,attack_end_frame,end_frame,"
                     "anchor_confident,anchor_input_sample,anchor_offset,"
                     "ideal_output_sample,mapped_peak_sample,"
                     "mapped_onset_sample,mapped_attack_end_sample\n";
        const auto& events = analysis.events();
        const auto& anchors = analysis.anchors();
        for (std::size_t i = 0; i < events.size(); ++i) {
            const auto& event = events[i];
            const auto& anchor = anchors[i];
            std::cout << i << ',' << event.onsetFrame << ','
                      << event.peakFrame << ',' << event.attackEndFrame << ','
                      << event.endFrame << ',' << int(anchor.confident) << ','
                      << std::setprecision(15) << anchor.absoluteInputSample << ','
                      << anchor.sampleOffset << ','
                      << frozen.idealStartAt(event.peakFrame) << ','
                      << map.starts().at(event.peakFrame) << ','
                      << map.starts().at(event.onsetFrame) << ','
                      << map.starts().at(event.attackEndFrame) << '\n';
        }
    } catch (const std::exception& error) {
        std::cerr << "Phase 38 event diagnostic: " << error.what() << '\n';
        return 1;
    }
}
