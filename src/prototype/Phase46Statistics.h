#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>
namespace ts::prototype {
inline std::array<double,3> phase46LatencySummary(std::vector<double> values) {
    values.erase(std::remove_if(values.begin(),values.end(),
        [](double v){return !std::isfinite(v) || v<0;}),values.end());
    if (values.empty()) return {-1,-1,-1};
    std::sort(values.begin(),values.end());
    const auto n=values.size();
    const double median=n%2 ? values[n/2] : (values[n/2-1]+values[n/2])/2.0;
    return {median,values[static_cast<std::size_t>(std::ceil(.95*n))-1],values.back()};
}
}
