#pragma once
#include <cstdint>
#include <stdexcept>

namespace ts::playback::progressive {
// v3 changes the native prepare link symbol too: mixing old headers and a new
// binary (or the reverse) fails at link time instead of reading a changed struct.
inline constexpr unsigned contractVersion=3;
struct ContractV3Tag {};
enum class FeaturePolicy : std::uint8_t {Disabled,ApprovedOnly,Research};
enum class AvailabilityReason : std::uint16_t {
    Available=0,NotConfigured=1,NotApproved=2,NoInput=3,InvalidState=4,
    InvalidContext=5,StaleContext=6,InvalidRange=7,MinimumInput=8,
    MinimumOutput=9,InvalidPolicy=10,WholeTrackRequired=11,
    ProtectedBoundary=12,RetiringOwner=13,PositionUnavailable=14,
    LimitReached=15,InputFailure=16,ResourceBudget=17,ResourceBusy=18,
    InvalidArgument=19,EngineFailure=20
};
inline const char* name(AvailabilityReason reason) noexcept {
    switch(reason){
#define TS_REASON(n) case AvailabilityReason::n:return #n
    TS_REASON(Available);TS_REASON(NotConfigured);TS_REASON(NotApproved);
    TS_REASON(NoInput);TS_REASON(InvalidState);TS_REASON(InvalidContext);
    TS_REASON(StaleContext);TS_REASON(InvalidRange);TS_REASON(MinimumInput);
    TS_REASON(MinimumOutput);TS_REASON(InvalidPolicy);TS_REASON(WholeTrackRequired);
    TS_REASON(ProtectedBoundary);TS_REASON(RetiringOwner);TS_REASON(PositionUnavailable);
    TS_REASON(LimitReached);TS_REASON(InputFailure);TS_REASON(ResourceBudget);
    TS_REASON(ResourceBusy);TS_REASON(InvalidArgument);TS_REASON(EngineFailure);
#undef TS_REASON
    }return "Unknown";
}
struct FeatureAvailability {
    bool implemented=true,approved=false,configured=false,effective=false,allowed=false;
    bool research=false;
    AvailabilityReason reason=AvailabilityReason::NotConfigured;
};
// Explicit v3 policy supersedes legacy booleans only when a host supplies it.
// ApprovedOnly never implicitly opts an unapproved method into research.
struct FeaturePolicyOptions {
    unsigned version=contractVersion;
    FeaturePolicy exactSeek=FeaturePolicy::ApprovedOnly;
    FeaturePolicy interactiveSeek=FeaturePolicy::ApprovedOnly;
    FeaturePolicy nativeLoops=FeaturePolicy::ApprovedOnly;
};
struct FeatureApprovals {
    // Per-method engine approval; app acceptance and acoustic approval are
    // separately recorded in the adoption ledger. Never inferred from opt-in.
    bool exactSeek=true,interactiveSeek=false,nativeLoops=false,currentCycleSpeed=false;
};
// Exact数値・所有権契約の承認。対応条件と根拠は採用台帳P06。
// Interactive/Loop/RT性能/アプリF・物理音響の承認へ拡張しない。
inline constexpr FeatureApprovals featureApprovals{};
inline FeatureAvailability resolveFeature(FeaturePolicy policy,bool approved) {
    if(policy!=FeaturePolicy::Disabled&&policy!=FeaturePolicy::ApprovedOnly&&policy!=FeaturePolicy::Research)
        throw std::invalid_argument("能力設定の方式が不正です");
    FeatureAvailability a;a.approved=approved;a.configured=policy!=FeaturePolicy::Disabled;
    a.research=policy==FeaturePolicy::Research;
    a.effective=a.configured&&(approved||a.research);
    a.reason=!a.configured?AvailabilityReason::NotConfigured:!a.effective?AvailabilityReason::NotApproved:AvailabilityReason::NoInput;
    return a;
}
inline void updateRuntime(FeatureAvailability& a,bool hasInput,bool validState,bool failed=false) noexcept {
    a.allowed=a.effective&&hasInput&&validState&&!failed;
    if(!a.effective)return;
    a.reason=failed?AvailabilityReason::EngineFailure:!hasInput?AvailabilityReason::NoInput:
        !validState?AvailabilityReason::InvalidState:AvailabilityReason::Available;
}
struct EffectiveFeatures {
    FeatureAvailability exactSeek,interactiveSeek,nativeLoops;
    std::uint64_t extraReservationBytes()const noexcept{return nativeLoops.effective?24ULL*1024*1024:0;}
};
inline EffectiveFeatures resolveFeatures(const FeaturePolicyOptions& p,FeatureApprovals approvals=featureApprovals) {
    if(p.version!=contractVersion)throw std::invalid_argument("能力契約の版が一致しません");
    return {resolveFeature(p.exactSeek,approvals.exactSeek),resolveFeature(p.interactiveSeek,approvals.interactiveSeek),resolveFeature(p.nativeLoops,approvals.nativeLoops)};
}
inline EffectiveFeatures legacyFeatures(bool loops,bool interactive) {
    return resolveFeatures({contractVersion,FeaturePolicy::Research,
        interactive?FeaturePolicy::Research:FeaturePolicy::Disabled,
        loops?FeaturePolicy::Research:FeaturePolicy::Disabled});
}
}
