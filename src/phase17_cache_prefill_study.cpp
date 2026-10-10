#include "audio/WavStream.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <sys/resource.h>
#include <vector>

// Independent cache-read/FIFO-prefill measurement. No production seek path is modified.
int main(int argc,char** argv) {
    try {
        if (argc!=4) throw std::invalid_argument("cache.wav golden.wav output.csv");
        ts::WavStreamReader cache(argv[1]),golden(argv[2]);
        if (cache.channels()!=golden.channels() || cache.sampleRate()!=golden.sampleRate() ||
            cache.frames()!=golden.frames()) throw std::runtime_error("Cache metadata mismatch");
        constexpr std::size_t prefill=16384;
        ts::Phase14AudioFifo fifo(cache.channels(),131072);
        std::vector<std::vector<float>> samples(cache.channels(),std::vector<float>(prefill));
        std::vector<std::vector<float>> check(cache.channels(),std::vector<float>(4096));
        std::vector<const float*> in(cache.channels());
        std::vector<float*> out(cache.channels());
        for (std::size_t c=0;c<cache.channels();++c) {in[c]=samples[c].data();out[c]=check[c].data();}
        std::vector<std::pair<const char*,std::size_t>> positions;
        const auto total=cache.frames();
        for (const auto [kind,fraction]:std::array<std::pair<const char*,double>,13>{{
            {"start",0.0},{"start",0.01},{"start",0.10},
            {"middle",0.45},{"middle",0.50},{"middle",0.55},
            {"end",0.90},{"end",0.95},{"end",0.99},
            {"rapid",0.75},{"rapid",0.25},{"rapid",0.80},{"rapid",0.15}}})
            positions.emplace_back(kind,std::min(total-1,static_cast<std::size_t>(total*fraction)));
        std::mt19937 rng(17);
        std::uniform_int_distribution<std::size_t> dist(0,total-1);
        for (int i=0;i<200;++i) positions.emplace_back("rapid_repeat",dist(rng));
        std::ofstream csv(argv[3]);
        if (!csv) throw std::runtime_error("Cannot open CSV");
        csv << "kind,output_frame,prefill_seconds,cpu_seconds,max_abs_difference,peak_rss_bytes,underrun_frames,rejected_writes\n";
        for (const auto& [kind,frame]:positions) {
            fifo.clearQuiescent();
            const auto count=std::min(prefill,total-frame);
            rusage before{},after{};
            getrusage(RUSAGE_SELF,&before);
            const auto begin=std::chrono::steady_clock::now();
            for (std::size_t i=0;i<count;++i)
                for (std::size_t c=0;c<cache.channels();++c)
                    samples[c][i]=cache.sample(c,frame+i);
            if (!fifo.write(in.data(),count)) throw std::runtime_error("FIFO write rejected");
            const double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
            getrusage(RUSAGE_SELF,&after);
            const double cpu=(after.ru_utime.tv_sec-before.ru_utime.tv_sec)+
                (after.ru_utime.tv_usec-before.ru_utime.tv_usec)*1e-6+
                (after.ru_stime.tv_sec-before.ru_stime.tv_sec)+
                (after.ru_stime.tv_usec-before.ru_stime.tv_usec)*1e-6;
            const auto verify=std::min<std::size_t>(4096,count);
            if (fifo.read(out.data(),verify)!=verify) throw std::runtime_error("FIFO underrun");
            double difference=0;
            for (std::size_t c=0;c<cache.channels();++c)
                for (std::size_t i=0;i<verify;++i)
                    difference=std::max(difference,std::abs(double(check[c][i])-golden.sample(c,frame+i)));
            csv << kind << ',' << frame << ',' << wall << ',' << cpu << ',' << difference << ','
                << after.ru_maxrss << ",0," << fifo.rejectedWrites() << '\n';
            if (difference!=0 || fifo.rejectedWrites())
                throw std::runtime_error("Cache differed from Golden or FIFO rejected write");
        }
        std::cout << "seek_count=" << positions.size() << " max_abs_difference=0\n";
    } catch (const std::exception& error) {
        std::cerr << "Phase 17 cache prefill study: " << error.what() << '\n';
        return 1;
    }
}
