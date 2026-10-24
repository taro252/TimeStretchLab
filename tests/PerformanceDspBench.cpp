// B1/B2の寄与だけを分ける通常threadの小試験。音声/RT/曲全体の性能承認ではない。
#include "prototype/Phase35PhaseVocoder.h"
#include "prototype/Phase35StereoPhaseCoherence.h"
#include "reference/performance_response/Frozen5674PhaseVocoder.h"
#include "reference/performance_response/Frozen5674StereoPhaseCoherence.h"
#include <array>
#include <algorithm>
#include <bit>
#include <cmath>
#include <ctime>
#include <chrono>
#include <iostream>
#include <iomanip>
#include <tuple>
#include <type_traits>
using namespace ts::prototype;
double cpu(){timespec t{};clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec+t.tv_nsec*1e-9;}
template<bool frozen,bool share> auto run(std::size_t n,unsigned frames){
    using P=std::conditional_t<frozen,Frozen5674PhaseVocoder,Phase35PhaseVocoder>;
    using C=std::conditional_t<frozen,Frozen5674StereoPhaseCoherence,Phase35StereoPhaseCoherence>;
    const auto bins=n/2+1;std::array<std::vector<std::complex<float>>,2> input,output;
    std::vector<int> owners(bins);for(auto& v:input)v.resize(bins);for(auto& v:output)v.resize(bins);
    for(std::size_t k=0;k<bins;++k){owners[k]=int(std::min(bins-1,std::max(std::size_t(1),(k/7)*7+3)));
        for(unsigned c=0;c<2;++c)input[c][k]=std::polar(float(.1+((k*19+c*13)%997)/13.),float((k*17+c*7)%1000)*.006f);}
    P l(n,n/4,true,48000),r(n,n/4,true,48000);C coherence(n,48000,.6f,.5f);
    const auto start=std::chrono::steady_clock::now();const auto startCpu=cpu();
    for(unsigned i=0;i<frames;++i){
        l.process(input[0].data(),output[0].data(),n/4,false,false,1,&owners);
        r.process(input[1].data(),output[1].data(),n/4,false,false,1,&owners);
        if constexpr(frozen)coherence.process(input[0].data(),input[1].data(),output[0].data(),output[1].data(),l,r,owners);
        else if constexpr(share){const auto a=l.inputPolarView(),b=r.inputPolarView();coherence.process(input[0].data(),input[1].data(),output[0].data(),output[1].data(),l,r,owners,&a,&b);}
        else coherence.process(input[0].data(),input[1].data(),output[0].data(),output[1].data(),l,r,owners);
    }
    const auto used=cpu()-startCpu;const auto wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::uint64_t digest=14695981039346656037ULL;for(const auto& channel:output)for(auto value:channel){
        if(!std::isfinite(value.real())||!std::isfinite(value.imag()))throw std::runtime_error("Nonfinite benchmark PCM");
        digest^=std::bit_cast<std::uint64_t>(value);digest*=1099511628211ULL;
    }
    return std::tuple{used,wall,digest};
}
int main(){try{std::cout<<std::setprecision(12);unsigned count=0;
    for(unsigned repeat=0;repeat<3;++repeat)for(auto n:{1024u,4096u,8192u}){
        std::uint64_t expected=0;
        // 前後を交互にする。入力・frame数・初期化は各標本で同じ。
        for(unsigned turn=0;turn<3;++turn){const auto mode=repeat%2?2-turn:turn;
            const auto [c,w,h]=mode==0?run<true,false>(n,512):mode==1?run<false,false>(n,512):run<false,true>(n,512);
            if(turn&&h!=expected)throw std::runtime_error("Benchmark final spectrum differs");expected=h;
            std::cout<<"{\"repeat\":"<<repeat<<",\"fft\":"<<n<<",\"mode\":"<<mode<<",\"frames\":512,\"cpu_s\":"<<c<<",\"wall_s\":"<<w<<",\"spectrum_fnv\":"<<h<<"}\n";++count;
        }
    }
    std::cout<<"SUMMARY {\"PASS\":true,\"expected\":27,\"executed\":"<<count<<",\"scope\":\"scalar DSP only\"}\n";return count==27?0:1;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
