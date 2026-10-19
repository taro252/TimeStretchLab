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
}
