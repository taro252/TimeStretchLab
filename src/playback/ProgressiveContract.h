#pragma once
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace ts::playback::progressive {
enum class State { Empty, Accepted, Preparing, Ready, Playing, Paused, Draining, Ended, Stopped, Failed };
inline const char* name(State s) noexcept {
    switch(s) {
    case State::Empty:return "Empty"; case State::Accepted:return "Accepted";
    case State::Preparing:return "Preparing"; case State::Ready:return "Ready";
    case State::Playing:return "Playing"; case State::Paused:return "Paused";
    case State::Draining:return "Draining"; case State::Ended:return "Ended";
    case State::Stopped:return "Stopped"; case State::Failed:return "Failed";
    } return "Unknown";
}
inline std::uint32_t speedMicros(double speed) {
    if(!std::isfinite(speed)||speed<.40||speed>2.00)throw std::invalid_argument("速度は0.40〜2.00倍です");
    const auto percent=std::llround(speed*100);
    if(std::abs(speed*100-percent)>1e-8)throw std::invalid_argument("速度は1%刻みです");
    return static_cast<std::uint32_t>(percent)*10000;
}
struct Capabilities {
    unsigned contractVersion=1,minSpeedPercent=40,maxSpeedPercent=200,speedStepPercent=1;
    bool experimental=true,seek=false,dynamicSpeed=true,incrementalReady=true;
    unsigned maxConcurrentSessions=1,maxSnapshots=3,maxDynamicMaps=3,maxAppliedPlans=512,maxOperations=4096;
    std::uint64_t maxInputBytes=512ULL*1024*1024,maxInputFrames=48000ULL*600;
};
// Admission reservation, not an allocator or RSS measurement. A single owner
// covers prepare, play and pause in this process; EOS/stop release the input.
inline std::uint64_t reservationBytes(std::uint64_t bytes,std::uint64_t frames) {
    const Capabilities c;
    if(!bytes||bytes>c.maxInputBytes||!frames||frames>c.maxInputFrames)
        throw std::length_error("実験用入力のサイズ・長さ上限を超えています");
    return bytes+256ULL*1024*1024+((frames+1023)/1024)*4096;
}
struct SupplyQuality {
    bool failed=false;
    static SupplyQuality evaluate(std::uint64_t missing,std::uint64_t calls,std::uint64_t rejected) noexcept {
        return {missing!=0||calls!=0||rejected!=0};
    }
};
}
