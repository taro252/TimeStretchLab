#pragma once
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <numbers>
namespace ts::prototype::phase61 {
// One DSP producer. Control only changes the atomic target; the callback never
// performs envelope arithmetic. Storage and the 5ms curve are prepared normally.
class PublicationEnvelope {
    std::size_t frames_,channels_,index_=0;
    std::array<float,241> curve_{};
    std::array<std::array<float,2048>,2> pcm_{};
    std::array<const float*,2> pointers_{};
    bool observed_=false,ramping_=false;
    float gain_=1,from_=1,goal_=1;
public:
    std::atomic<bool> retireRequested{false};
    std::atomic<std::size_t> retireEnd{0};
    PublicationEnvelope(std::size_t rate,std::size_t channels):frames_(rate/200),channels_(channels){
        for(std::size_t i=0;i<frames_;++i)curve_[i]=float(.5-.5*std::cos(std::numbers::pi*i/(frames_-1)));
        for(std::size_t c=0;c<channels_;++c)pointers_[c]=pcm_[c].data();
    }
    const float*const* apply(const float*const* input,std::size_t at,std::size_t n,bool fadeIn,std::size_t start)noexcept{
        const bool requested=retireRequested.load();
        if(requested!=observed_){observed_=requested;ramping_=true;index_=0;from_=gain_;goal_=requested?0.f:1.f;retireEnd=requested?at+frames_:0;}
        if(!(fadeIn&&at<start+frames_)&&!ramping_&&gain_==1)return input;
        for(std::size_t i=0;i<n;++i){
            if(ramping_){gain_=from_+(goal_-from_)*curve_[index_];if(++index_==frames_){gain_=goal_;ramping_=false;}}
            float gain=gain_;
            if(fadeIn&&at+i>=start&&at+i-start<frames_)gain*=curve_[at+i-start];
            for(std::size_t c=0;c<channels_;++c)pcm_[c][i]=input[c][i]*gain;
        }
        return pointers_.data();
    }
};
}
