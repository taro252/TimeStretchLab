#pragma once
#include "dsp/TransientEventMap.h"
#include <cstddef>
#include <vector>

namespace ts {
// One logical output timeline, sampled at the mid-resolution analysis frames.
// Other resolutions interpolate it at their own input-sample positions.
class TimeMap {
public:
    TimeMap() = default;
    TimeMap(int sourceHop, std::vector<long long> starts,
            std::vector<TransientEvent> events);
    double outputPositionForInputSample(double inputSample) const;
    const std::vector<TransientEvent>& events() const { return events_; }
    int sourceHop() const { return sourceHop_; }
    bool empty() const { return starts_.empty(); }
private:
    int sourceHop_ = 1;
    std::vector<long long> starts_;
    std::vector<TransientEvent> events_;
};
}
