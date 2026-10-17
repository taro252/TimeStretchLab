#pragma once
#include <array>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <atomic>
#include <stdexcept>

namespace ts::prototype::phase61 {
// Only normal owner calls prepare while no render can refer to this slot.
// One audio consumer advances cursor, no cursor resets on a live FIFO.
enum class SwitchPhase : unsigned {Idle,Requested,Started,Done,Cancelled};
static_assert(std::atomic<SwitchPhase>::is_always_lock_free);
class OutputTransition {
    std::array<float,241> incoming_{};
public:
    std::array<std::array<float,241>,2> oldPcm{};
    std::size_t length=0,cursor=0;
    void prepare(std::uint32_t rate){
        if(rate!=44100&&rate!=48000)throw std::invalid_argument("Interactive supports 44.1/48kHz");
        length=rate/200;cursor=0;
        for(std::size_t i=0;i<length;++i)incoming_[i]=float(i+1)/float(length);
        // Touch all scratch before publishing; no demand-zero first touch.
        for(auto& c:oldPcm)c.fill(0);
    }
    std::size_t remaining()const noexcept{return length-cursor;}
    void mix(float*const* output,std::size_t frames,std::size_t channels)noexcept{
        for(std::size_t i=0;i<frames;++i){const auto gain=incoming_[cursor+i];
            for(std::size_t c=0;c<channels;++c)output[c][i]=oldPcm[c][i]*(1.f-gain)+output[c][i]*gain;
        }cursor+=frames;
    }
};
}
