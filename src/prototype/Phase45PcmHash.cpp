#include "audio/WavStream.h"
#include "prototype/Phase45PcmDigest.h"
#include <bit>
#include <cstdint>
#include <cmath>
#include <iostream>
#include <limits>
int main(int argc,char** argv) {
    try {
        if (argc!=2 && argc!=3) return 2;
        ts::WavStreamReader input(argv[1]);
        std::uint64_t hash=14695981039346656037ULL,nonfinite=0;
        ts::prototype::Phase45PcmDigest digest;
        std::vector<float> block(4096*input.channels());
        std::size_t filled=0;
        for (std::size_t i=0;i<input.frames();++i)
            for (std::size_t c=0;c<input.channels();++c) {
                const auto value=input.sample(c,i);
                block[filled++]=value;
                if (filled==block.size()) {
                    digest.update(block.data(),filled*sizeof(float));filled=0;
                }
                nonfinite+=!std::isfinite(value);
                hash^=std::bit_cast<std::uint32_t>(value);hash*=1099511628211ULL;
            }
        digest.update(block.data(),filled*sizeof(float));
        std::cout<<"pcm_fingerprint="<<std::hex<<hash<<std::dec
                 <<"\nframes="<<input.frames()<<"\nnonfinite="<<nonfinite<<'\n';
        std::cout<<"pcm_sha256="<<digest.finish()<<'\n';
        if (argc==3) {
            ts::WavStreamReader fixed(argv[2]);
            if (input.channels()!=fixed.channels() || input.sampleRate()!=fixed.sampleRate()) return 1;
            auto first=std::numeric_limits<std::size_t>::max();
            for (std::size_t i=0;i<std::min(input.frames(),fixed.frames());++i)
                for (std::size_t c=0;c<input.channels();++c)
                    if (first==std::numeric_limits<std::size_t>::max() &&
                        std::bit_cast<std::uint32_t>(input.sample(c,i))!=
                        std::bit_cast<std::uint32_t>(fixed.sample(c,i))) first=i;
            std::cout<<"first_changed_pcm_frame=";
            if (first==std::numeric_limits<std::size_t>::max()) std::cout<<"none\n";
            else std::cout<<first<<'\n';
        }
        return nonfinite ? 1 : 0;
    } catch (const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
}
