#include "prototype/Phase61OutputTransition.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
using ts::prototype::phase61::OutputTransition;
void require(bool b,const char* m){if(!b)throw std::runtime_error(m);}
int main(){try{
    std::size_t cases=0;
    for(auto rate:{44100u,48000u})for(auto channels:{1u,2u})for(auto chunk:{1u,7u,64u,128u,512u,4096u})for(auto oldCount:{0u,17u,240u}){
        OutputTransition t;t.prepare(rate);std::array<std::array<float,4096>,2> pcm{};
        std::size_t freshConsumed=0;
        while(t.remaining()){
            const auto n=std::min<std::size_t>(chunk,t.remaining());float* p[]{pcm[0].data(),pcm[1].data()};const auto before=t.cursor;
            for(unsigned c=0;c<channels;++c)for(std::size_t i=0;i<n;++i){p[c][i]=float(freshConsumed+i+1)/1000;t.oldPcm[c][i]=before+i<oldCount?.25f:0.f;}
            t.mix(p,n,channels);
            for(unsigned c=0;c<channels;++c)for(std::size_t i=0;i<n;++i){const float gain=float(before+i+1)/float(t.length);
                const float expected=(before+i<oldCount?.25f:0.f)*(1.f-gain)+float(freshConsumed+i+1)/1000*gain;
                require(p[c][i]==expected&&std::isfinite(p[c][i]),"mix identity / EOF fallback");}
            freshConsumed+=n;
        }require(freshConsumed==rate/200,"lost/duplicated first new frame");++cases;
        // Identical correlated sources stay exactly at 1 with complementary gains.
        t.prepare(rate);for(unsigned c=0;c<channels;++c){pcm[c].fill(1.f);t.oldPcm[c].fill(1.f);}float* p[]{pcm[0].data(),pcm[1].data()};t.mix(p,t.length,channels);
        for(unsigned c=0;c<channels;++c)for(std::size_t i=0;i<t.length;++i)require(p[c][i]==1.f,"gain sum");
    }
    std::cout<<"PASS "<<cases<<" transition chunk/format/EOF cases, complementary gain, new prefix order\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
