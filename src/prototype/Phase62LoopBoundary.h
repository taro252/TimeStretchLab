#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
namespace ts::prototype::phase62 {
// Immutable output coordinates for ONE fixed-speed epoch, certified from its
// final TimeMap. Never extrapolate a B from a previous epoch or requested speed.
struct Boundary {
    std::uint64_t end=0;
    std::size_t fade=0;
    static std::size_t fadeLength(std::uint32_t rate,std::size_t oldLength,std::size_t newLength)noexcept{
        return std::min({std::size_t(rate/200),oldLength/4,newLength/4});
    }
    std::uint64_t fadeBegin()const noexcept{return end>=fade?end-fade:0;}
    std::size_t prefix(std::uint64_t position,std::size_t wanted)const noexcept{
        return position<fadeBegin()?std::min<std::uint64_t>(wanted,fadeBegin()-position):0;
    }
};
// Phase62 Fix: time-preserving local correction, not temporal overlap.
// RAW length L stays L. Only last/first N frames are modified; all references
// are from the two selected ranges. End samples share one exactly computed
// midpoint. Smoothstep returns the correction towards zero away from B/A.
struct PeriodBoundary {
    static constexpr std::size_t minimumFrames=512,maximumCallback=4096,maximumSpans=32;
    static std::size_t length(std::uint32_t rate,std::size_t frames)noexcept{return std::min<std::size_t>(rate/200,frames/4);}
    static float smooth(float t)noexcept{return t*t*(3.f-2.f*t);}
    static float midpoint(float last,float first)noexcept{return last*.5f+first*.5f;}
    static float tail(float raw,float last,float nextFirst,std::size_t at,std::size_t n)noexcept{
        if(at+1==n)return midpoint(last,nextFirst);
        return raw-(last-nextFirst)*.5f*smooth(float(at+1)/float(n));
    }
    static float head(float raw,float previousLast,float first,std::size_t at,std::size_t n)noexcept{
        if(!at)return midpoint(previousLast,first);
        return raw+(previousLast-first)*.5f*smooth(1.f-float(at)/float(n));
    }
};
static_assert(3*((PeriodBoundary::maximumCallback+PeriodBoundary::minimumFrames-1)/PeriodBoundary::minimumFrames+1)+1<=PeriodBoundary::maximumSpans);
}
