#include "audio/WavStream.h"
#include "dsp/STFT.h"
#include "dsp/TransientDetector.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

int main(int argc,char** argv) {
    if (argc!=3) {std::cerr << "Usage: phase101_offline_events input.wav events.csv\n";return 2;}
    try {
        ts::WavStreamReader reader(argv[1]);
        constexpr std::size_t size=4096,hop=1024,padding=size/2;
        const auto count=(reader.frames()+padding+hop-1)/hop+1;
        const auto active=reader.frames()+padding>=size
            ? (reader.frames()+padding-size)/hop+1:0;
        ts::STFT stft(size);
        ts::TransientDetector detector(size/2+1,{});
        std::vector<float> frame(size),combined(size/2+1);
        std::vector<std::complex<float>> spectrum(size/2+1);
        for (std::size_t index=0;index<count;++index) {
            std::fill(combined.begin(),combined.end(),0);
            for (std::size_t c=0;c<reader.channels();++c) {
                for (std::size_t n=0;n<size;++n) {
                    const auto at=static_cast<long long>(index*hop+n)-padding;
                    frame[n]=at>=0 && static_cast<std::size_t>(at)<reader.frames()
                        ? reader.sample(c,static_cast<std::size_t>(at)):0;
                }
                stft.analyze(frame.data(),spectrum.data());
                for (std::size_t k=0;k<combined.size();++k)
                    combined[k]+=std::norm(spectrum[k]);
            }
            for (auto& value:combined)value=std::sqrt(value);
            detector.pushMagnitudes(combined.data());
        }
        detector.finalize(active);
        ts::TransientEventMap map(detector.frames(),active,hop,2.0,{});
        std::ofstream file(argv[2]);
        if (!file)throw std::runtime_error("Cannot write event CSV");
        file << "peakFrame,inputSample,strength\n";
        for (const auto& event:map.events())
            file << event.peakFrame << ',' << event.peakFrame*hop << ','
                 << event.strength << '\n';
        std::cout << "events=" << map.events().size() << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';return 1;
    }
}
