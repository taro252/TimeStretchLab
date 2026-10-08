#include "dsp/TimeMap.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace ts {
TimeMap::TimeMap(int sourceHop, std::vector<long long> starts,
                 std::vector<TransientEvent> events)
    : sourceHop_(sourceHop), starts_(std::move(starts)), events_(std::move(events)) {
    if (sourceHop <= 0 || starts_.empty()) throw std::invalid_argument("Invalid time map");
}
double TimeMap::outputPositionForInputSample(double inputSample) const {
    if (starts_.empty() || !std::isfinite(inputSample) || inputSample < 0)
        throw std::invalid_argument("Invalid time map position");
    if (starts_.size() == 1) return starts_[0];
    const double fractional = inputSample / sourceHop_;
    const auto left = std::min(static_cast<std::size_t>(fractional), starts_.size()-2);
    const double local = fractional - left;
    return starts_[left] + local * double(starts_[left+1] - starts_[left]);
}
}
