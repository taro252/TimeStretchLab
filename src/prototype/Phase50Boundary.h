#pragma once
#include "prototype/Phase36StreamingSpeedEngine.h"
#include <algorithm>
#include <cmath>

namespace ts::prototype {
struct Phase50Boundary {
    std::size_t legacy=0, precise=0;
    std::array<std::size_t,3> processedNode{}, consumedOla{};
    std::array<std::size_t,2> consumedFir{};
};
// Read-only dependency audit. Frame starts use padded OLA coordinates;
// raw FIR source n uses OLA n + FFT/2. No history/state is reconstructed.
template<class Map> inline Phase50Boundary phase50Boundary(const Phase36StreamingSpeedEngine::Frontier& f,
                                      const Map& map,std::size_t published) {
    Phase50Boundary b;
    b.precise=b.legacy=std::max(f.preparedOutput,published);
    constexpr std::array<std::size_t,3> hop{2048,1024,256};
    for (std::size_t r=0;r<3;++r) {
        auto node=[&](std::size_t i) { return std::size_t(map.starts()[std::min(i,map.starts().size()-1)]); };
        b.processedNode[r]=node((f.lastProcessedInput[r]+1023)/1024);
        b.consumedOla[r]=f.finalizedOla[r];
        b.precise=std::max({b.precise,b.processedNode[r],b.consumedOla[r]});
        b.legacy=std::max({b.legacy,node(f.lastProcessedInput[r]/1024+1),
            node((f.nextInput[r]+hop[r]+1023)/1024),f.finalizedOla[r]});
    }
    // LP250 reads Low/Mid (max padding4096); LP3500 reads Mid/High (2048).
    b.consumedFir={f.firstUnprocessedFirSource[0]+4096,f.firstUnprocessedFirSource[1]+2048};
    b.precise=std::max({b.precise,b.consumedFir[0],b.consumedFir[1]});
    for (auto source:f.firstUnprocessedFirSource) b.legacy=std::max(b.legacy,source+4096);
    return b;
}
template<class Before,class After> inline bool phase50PreservesState(const Phase36StreamingSpeedEngine::Frontier& f,
                                 const Before& before,const After& after) {
    for (std::size_t r=0;r<3;++r) {
        const auto node=(f.lastProcessedInput[r]+1023)/1024;
        for (std::size_t i=0;i<=node && i<before.starts().size();++i)
            if (before.starts()[i]!=after.starts()[i]) return false;
        for (std::size_t i=0;i<f.recentFrameCount[r];++i)
            if (std::llround(after.outputPositionForInputSample(double(f.recentFrameInput[r][i])))
                !=f.recentFrameOutput[r][i]) return false;
        if (std::llround(after.outputPositionForInputSample(double(f.nextInput[r])))<
            static_cast<long long>(f.finalizedOla[r])) return false;
    }
    return true;
}
}
