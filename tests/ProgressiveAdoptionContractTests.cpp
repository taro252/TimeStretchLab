// 採用契約v3の純粋な値型・設定変換を検査する。Engine/装置/DSPは作らない。
// true承認は試験用入力だけに使い、製品のfeatureApprovals定数を変更しない。
#include "playback/ProgressiveContract.h"
#include "playback/ProgressiveLoopContract.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <type_traits>
#include <utility>

namespace {
namespace contract = ts::playback::progressive;
using Policy = contract::FeaturePolicy;
using Reason = contract::AvailabilityReason;
using Availability = contract::FeatureAvailability;
constexpr std::uint64_t mib = 1024ULL * 1024;
constexpr std::uint64_t loopReservation = 24 * mib;
constexpr std::array<const char*,20> checkIDs{
    "D4.version_and_policy_defaults",
    "D4.production_approvals_not_inferred",
    "D4.single_feature_truth_table",
    "D4.policy_approval_cartesian",
    "D4.exact_approval_isolation",
    "D4.loop_approval_isolation",
    "D4.interactive_approval_isolation",
    "D4.current_cycle_approval_isolation",
    "D4.legacy_optin_matrix",
    "D4.legacy_false_remains_disabled",
    "D4.invalid_policy_values",
    "D4.invalid_composite_policy_values",
    "D4.invalid_versions",
    "D4.runtime_matrix_and_recovery",
    "D4.runtime_feature_independence",
    "D4.capabilities_v3_limits",
    "D4.stable_reasons_and_legacy_receipts",
    "D5.reservation_configuration_derivation",
    "D5.reservation_input_boundaries",
    "D5.reservation_runtime_independence"
};
void need(bool value, const std::string& why) {
    if (!value) throw std::runtime_error(why);
}
template<class Exception, class Function>
void rejects(Function function, const char* why) {
    bool rejected = false;
    try { function(); }
    catch (const Exception&) { rejected = true; }
    need(rejected, why);
}
bool same(const Availability& a, const Availability& b) {
    return std::tie(a.implemented,a.approved,a.configured,a.effective,a.allowed,a.research,a.reason) ==
           std::tie(b.implemented,b.approved,b.configured,b.effective,b.allowed,b.research,b.reason);
}
bool same(const contract::EffectiveFeatures& a, const contract::EffectiveFeatures& b) {
    return same(a.exactSeek,b.exactSeek) && same(a.interactiveSeek,b.interactiveSeek) &&
           same(a.nativeLoops,b.nativeLoops) && a.extraReservationBytes()==b.extraReservationBytes();
}

// 製品関数の式を再実装せず、3方式×承認2通りの期待値を列挙する。
struct Truth {
    Policy policy;
    bool approved,configured,effective,research;
    Reason initialReason;
};
constexpr std::array<Truth,6> truth{
    Truth{Policy::Disabled,     false,false,false,false,Reason::NotConfigured},
    Truth{Policy::Disabled,     true, false,false,false,Reason::NotConfigured},
    Truth{Policy::ApprovedOnly, false,true, false,false,Reason::NotApproved},
    Truth{Policy::ApprovedOnly, true, true, true, false,Reason::NoInput},
    Truth{Policy::Research,     false,true, true, true, Reason::NoInput},
    Truth{Policy::Research,     true, true, true, true, Reason::NoInput}
};
constexpr std::array<Policy,3> policies{Policy::Disabled,Policy::ApprovedOnly,Policy::Research};
const Truth& expectation(Policy policy, bool approved) {
    for (const auto& row : truth)
        if (row.policy==policy && row.approved==approved) return row;
    throw std::logic_error("期待表にない方式・承認");
}
void metadata(const Availability& a, const Truth& row) {
    need(a.implemented && a.approved==row.approved && a.configured==row.configured &&
         a.effective==row.effective && a.research==row.research,
         "実装・承認・設定・有効性・研究設定が期待表と不一致");
}
void initial(const Availability& a, const Truth& row) {
    metadata(a,row);
    need(!a.allowed && a.reason==row.initialReason, "入力未取得時の許可・理由が不一致");
}
contract::FeatureApprovals approvals(unsigned mask) {
    return {bool(mask&1),bool(mask&2),bool(mask&4),bool(mask&8)};
}
contract::FeaturePolicyOptions options(Policy exact, Policy interactive, Policy loops) {
    return {contract::contractVersion,exact,interactive,loops};
}
void allRuntime(contract::EffectiveFeatures& features, bool input, bool state, bool failed=false) {
    contract::updateRuntime(features.exactSeek,input,state,failed);
    contract::updateRuntime(features.interactiveSeek,input,state,failed);
    contract::updateRuntime(features.nativeLoops,input,state,failed);
}
struct Runtime {
    bool hasInput,validState,failed,allowed;
    Reason reason;
};
// 全8組を含み、Available→失敗→Availableも同一オブジェクトで通る。
constexpr std::array<Runtime,10> runtime{
    Runtime{true, true, false,true, Reason::Available},
    Runtime{false,false,false,false,Reason::NoInput},
    Runtime{false,true, false,false,Reason::NoInput},
    Runtime{true, false,false,false,Reason::InvalidState},
    Runtime{false,false,true, false,Reason::EngineFailure},
    Runtime{false,true, true, false,Reason::EngineFailure},
    Runtime{true, false,true, false,Reason::EngineFailure},
    Runtime{true, true, true, false,Reason::EngineFailure},
    Runtime{true, true, false,true, Reason::Available},
    Runtime{false,false,false,false,Reason::NoInput}
};
void runtimeValue(const Availability& a, const Truth& row, const Runtime& state) {
    metadata(a,row);
    need(a.allowed==(row.effective && state.allowed), "実行時許可が期待表と不一致");
    need(a.reason==(row.effective ? state.reason : row.initialReason),
         "実行時理由の優先順位、設定無効、承認待ちの保持が不一致");
}

struct Reporter {
    std::size_t passed=0;
    void expected() const {
        std::cout << "{\"record\":\"expected\",\"schema\":1,\"contract_version\":3,\"expected\":"
                  << checkIDs.size() << ",\"required_ids\":[";
        for (std::size_t i=0;i<checkIDs.size();++i)
            std::cout << (i?",":"") << '"' << checkIDs[i] << '"';
        std::cout << "],\"audio\":false,\"engine_created\":false}\n";
    }
    void pass(const char* id, std::size_t cases) {
        need(passed<checkIDs.size() && std::string_view(checkIDs[passed])==id,
             "固定check IDの順序・集合が不一致");
        ++passed;
        std::cout << "{\"id\":\"" << id << "\",\"status\":\"PASS\",\"cases\":"
                  << cases << "}\n";
    }
};
}

int main() {
    Reporter report;
    report.expected();
    try {
        {
            static_assert(std::is_empty_v<contract::ContractV3Tag>);
            const contract::FeaturePolicyOptions p;
            need(contract::contractVersion==3 && p.version==3, "契約版はv3");
            need(p.exactSeek==Policy::ApprovedOnly && p.interactiveSeek==Policy::ApprovedOnly &&
                 p.nativeLoops==Policy::ApprovedOnly, "正式設定の既定はApprovedOnly");
            need(unsigned(Policy::Disabled)==0 && unsigned(Policy::ApprovedOnly)==1 &&
                 unsigned(Policy::Research)==2, "方式の既存数値が変化");
            const auto f=contract::resolveFeatures(p);
            initial(f.exactSeek,expectation(p.exactSeek,contract::featureApprovals.exactSeek));
            initial(f.interactiveSeek,expectation(p.interactiveSeek,contract::featureApprovals.interactiveSeek));
            initial(f.nativeLoops,expectation(p.nativeLoops,contract::featureApprovals.nativeLoops));
            report.pass("D4.version_and_policy_defaults",1);
        }
        {
            // 製品承認が将来証拠付きで変更されても、opt-inから推定することは許さない。
            const auto declared=contract::featureApprovals;
            const auto research=contract::resolveFeatures(options(Policy::Research,Policy::Research,Policy::Research));
            need(research.exactSeek.approved==declared.exactSeek &&
                 research.interactiveSeek.approved==declared.interactiveSeek &&
                 research.nativeLoops.approved==declared.nativeLoops, "Researchが製品承認を昇格");
            const auto unapproved=contract::resolveFeatures(
                options(Policy::Research,Policy::Research,Policy::Research),{false,false,false,false});
            need(!unapproved.exactSeek.approved && !unapproved.interactiveSeek.approved &&
                 !unapproved.nativeLoops.approved, "試験用未承認が承認済みへ変化");
            need(unapproved.exactSeek.effective && unapproved.interactiveSeek.effective &&
                 unapproved.nativeLoops.effective, "研究利用と正式承認を混同");
            report.pass("D4.production_approvals_not_inferred",2);
        }
        {
            for (const auto& row : truth)
                initial(contract::resolveFeature(row.policy,row.approved),row);
            report.pass("D4.single_feature_truth_table",truth.size());
        }
        {
            std::size_t cases=0;
            for (const auto exact : policies) for (const auto interactive : policies)
                for (const auto loops : policies) for (unsigned mask=0;mask<16;++mask) {
                    const auto a=approvals(mask);
                    const auto f=contract::resolveFeatures(options(exact,interactive,loops),a);
                    initial(f.exactSeek,expectation(exact,a.exactSeek));
                    initial(f.interactiveSeek,expectation(interactive,a.interactiveSeek));
                    const auto& loopRow=expectation(loops,a.nativeLoops);
                    initial(f.nativeLoops,loopRow);
                    need(f.extraReservationBytes()==(loopRow.effective?loopReservation:0),
                         "policy/承認の全組合せで追加予約が不一致");
                    ++cases;
                }
            need(cases==432, "policy/承認の全組合せを網羅していない");
            report.pass("D4.policy_approval_cartesian",cases);
        }
        {
            auto f=contract::resolveFeatures(contract::FeaturePolicyOptions{}, {true,false,false,false});
            allRuntime(f,true,true);
            need(f.exactSeek.allowed && f.exactSeek.approved, "Exact単独承認が有効にならない");
            need(!f.interactiveSeek.approved && !f.interactiveSeek.allowed &&
                 f.interactiveSeek.reason==Reason::NotApproved && !f.nativeLoops.allowed &&
                 f.extraReservationBytes()==0, "Exact単独承認が他機能へ漏れた");
            report.pass("D4.exact_approval_isolation",1);
        }
        {
            auto f=contract::resolveFeatures(contract::FeaturePolicyOptions{}, {false,false,true,false});
            allRuntime(f,true,true);
            need(f.nativeLoops.allowed && f.nativeLoops.approved &&
                 f.extraReservationBytes()==loopReservation, "Loop単独承認・予約が不一致");
            need(!f.interactiveSeek.approved && !f.interactiveSeek.allowed &&
                 f.interactiveSeek.reason==Reason::NotApproved && !f.exactSeek.allowed,
                 "Loop単独承認がInteractive/Exactへ漏れた");
            report.pass("D4.loop_approval_isolation",1);
        }
        {
            auto f=contract::resolveFeatures(contract::FeaturePolicyOptions{}, {false,true,false,false});
            allRuntime(f,true,true);
            need(f.interactiveSeek.allowed && f.interactiveSeek.approved, "Interactive単独承認が無効");
            need(!f.exactSeek.allowed && !f.nativeLoops.allowed && f.extraReservationBytes()==0,
                 "Interactive単独承認がExact/Loopへ漏れた");
            report.pass("D4.interactive_approval_isolation",1);
        }
        {
            std::size_t cases=0;
            for (const auto exact : policies) for (const auto interactive : policies)
                for (const auto loops : policies) for (unsigned mask=0;mask<8;++mask) {
                    const auto p=options(exact,interactive,loops);
                    const auto without=contract::resolveFeatures(p,approvals(mask));
                    const auto with=contract::resolveFeatures(p,approvals(mask|8));
                    need(same(without,with), "現在周期速度の承認が別機能の承認・設定へ漏れた");
                    ++cases;
                }
            need(cases==216, "現在周期承認の独立性の組合せ不足");
            report.pass("D4.current_cycle_approval_isolation",cases);
        }
        {
            std::size_t cases=0;
            for (bool loops : {false,true}) for (bool interactive : {false,true}) {
                auto f=contract::legacyFeatures(loops,interactive);
                initial(f.exactSeek,expectation(Policy::Research,contract::featureApprovals.exactSeek));
                initial(f.interactiveSeek,expectation(interactive?Policy::Research:Policy::Disabled,
                                                     contract::featureApprovals.interactiveSeek));
                initial(f.nativeLoops,expectation(loops?Policy::Research:Policy::Disabled,
                                                 contract::featureApprovals.nativeLoops));
                allRuntime(f,true,true);
                need(f.exactSeek.allowed && f.interactiveSeek.allowed==interactive &&
                     f.nativeLoops.allowed==loops &&
                     f.extraReservationBytes()==(loops?loopReservation:0),
                     "旧opt-inの4通りの意味が変化");
                ++cases;
            }
            report.pass("D4.legacy_optin_matrix",cases);
        }
        {
            auto f=contract::legacyFeatures(false,false);
            for (const auto& state : runtime) {
                allRuntime(f,state.hasInput,state.validState,state.failed);
                need(!f.nativeLoops.configured && !f.nativeLoops.effective && !f.nativeLoops.allowed &&
                     !f.interactiveSeek.configured && !f.interactiveSeek.effective &&
                     !f.interactiveSeek.allowed && f.extraReservationBytes()==0 &&
                     f.nativeLoops.reason==Reason::NotConfigured &&
                     f.interactiveSeek.reason==Reason::NotConfigured,
                     "旧falseが現在状態から暗黙に有効化された");
            }
            // 承認済みでも明示Disabledは維持する（試験用承認）。
            const auto disabled=contract::resolveFeatures(
                options(Policy::Disabled,Policy::Disabled,Policy::Disabled),{true,true,true,true});
            need(!disabled.exactSeek.effective && !disabled.interactiveSeek.effective &&
                 !disabled.nativeLoops.effective && disabled.extraReservationBytes()==0,
                 "明示無効を承認が上書き");
            report.pass("D4.legacy_false_remains_disabled",runtime.size()+1);
        }
        {
            std::size_t cases=0;
            for (unsigned raw=3;raw<=std::numeric_limits<std::uint8_t>::max();++raw)
                for (bool approved : {false,true}) {
                    rejects<std::invalid_argument>([&] {
                        (void)contract::resolveFeature(static_cast<Policy>(raw),approved);
                    }, "不正FeaturePolicyを受理");
                    ++cases;
                }
            need(cases==506, "不正uint8方式の全値を検査していない");
            report.pass("D4.invalid_policy_values",cases);
        }
        {
            std::size_t cases=0;
            for (unsigned field=0;field<3;++field)
                for (unsigned raw=3;raw<=std::numeric_limits<std::uint8_t>::max();++raw) {
                    auto p=contract::FeaturePolicyOptions{};
                    if (field==0) p.exactSeek=static_cast<Policy>(raw);
                    else if (field==1) p.interactiveSeek=static_cast<Policy>(raw);
                    else p.nativeLoops=static_cast<Policy>(raw);
                    rejects<std::invalid_argument>([&] { (void)contract::resolveFeatures(p); },
                                                   "複合設定の不正方式を受理");
                    ++cases;
                }
            need(cases==759, "複合設定の全不正方式の検査不足");
            report.pass("D4.invalid_composite_policy_values",cases);
        }
        {
            std::size_t cases=0;
            const auto rejectVersion=[&](unsigned version) {
                auto p=contract::FeaturePolicyOptions{};p.version=version;
                rejects<std::invalid_argument>([&] { (void)contract::resolveFeatures(p); },
                                               "不一致の契約版を受理");
                ++cases;
            };
            for (unsigned version=0;version<=255;++version)
                if (version!=3) rejectVersion(version);
            rejectVersion(std::numeric_limits<unsigned>::max());
            need(cases==256, "不一致版の検査不足");
            report.pass("D4.invalid_versions",cases);
        }
        {
            std::size_t cases=0;
            for (const auto& row : truth) {
                auto reused=contract::resolveFeature(row.policy,row.approved);
                for (const auto& state : runtime) {
                    auto fresh=contract::resolveFeature(row.policy,row.approved);
                    contract::updateRuntime(fresh,state.hasInput,state.validState,state.failed);
                    contract::updateRuntime(reused,state.hasInput,state.validState,state.failed);
                    runtimeValue(fresh,row,state);runtimeValue(reused,row,state);
                    need(same(fresh,reused), "過去の実行状態が次の許可・理由へ残存");
                    ++cases;
                }
            }
            need(cases==60, "全runtime組合せ・回復の検査不足");
            report.pass("D4.runtime_matrix_and_recovery",cases);
        }
        {
            auto f=contract::resolveFeatures(options(Policy::Research,Policy::Research,Policy::Research),
                                             {false,false,false,false});
            const auto before=f;
            contract::updateRuntime(f.exactSeek,true,true);
            need(f.exactSeek.allowed && same(f.interactiveSeek,before.interactiveSeek) &&
                 same(f.nativeLoops,before.nativeLoops), "Exact照会が他機能を更新");
            contract::updateRuntime(f.interactiveSeek,true,true,true);
            need(f.exactSeek.allowed && !f.interactiveSeek.allowed &&
                 f.interactiveSeek.reason==Reason::EngineFailure &&
                 same(f.nativeLoops,before.nativeLoops), "Interactive失敗が他機能へ漏れた");
            contract::updateRuntime(f.nativeLoops,false,false);
            need(f.exactSeek.allowed && f.nativeLoops.reason==Reason::NoInput &&
                 f.extraReservationBytes()==loopReservation, "機能別runtime更新・予約の独立性");
            report.pass("D4.runtime_feature_independence",3);
        }
        {
            const contract::Capabilities c;
            need(c.contractVersion==3 && contract::SeekAvailability{}.contractVersion==3 &&
                 contract::LoopAvailability{}.contractVersion==3, "公開能力の版不一致");
            need(c.experimental && !c.seek && c.seekRequests && c.dynamicSpeed && c.incrementalReady,
                 "旧能力boolの意味を新方式の一括承認へ変更");
            need(c.minSpeedPercent==40 && c.maxSpeedPercent==200 && c.speedStepPercent==1 &&
                 c.maxConcurrentSessions==1 && c.maxSnapshots==3 && c.maxDynamicMaps==3 &&
                 c.maxAppliedPlans==512 && c.maxOperations==4096 && c.maxSeekOperations==4096 &&
                 c.maxRenderEpochs==2 && c.maxCheckpointStates==2 &&
                 c.maxInputBytes==512*mib && c.maxInputFrames==48000ULL*600, "公開資源・速度上限が変化");
            need(contract::LoopAvailability{}.minimumInputMillis==100 &&
                 contract::LoopAvailability{}.maximumCallbackFrames==4096, "Loopの入出力下限・callback上限");
            unsigned speeds=0;
            for (unsigned percent=40;percent<=200;++percent) {
                need(contract::speedMicros(percent/100.)==percent*10000, "161速度の数値契約");
                ++speeds;
            }
            need(speeds==161, "速度値の件数");
            report.pass("D4.capabilities_v3_limits",speeds);
        }
        {
            constexpr std::array<std::pair<Reason,std::string_view>,21> reasons{{
                {Reason::Available,"Available"},{Reason::NotConfigured,"NotConfigured"},
                {Reason::NotApproved,"NotApproved"},{Reason::NoInput,"NoInput"},
                {Reason::InvalidState,"InvalidState"},{Reason::InvalidContext,"InvalidContext"},
                {Reason::StaleContext,"StaleContext"},{Reason::InvalidRange,"InvalidRange"},
                {Reason::MinimumInput,"MinimumInput"},{Reason::MinimumOutput,"MinimumOutput"},
                {Reason::InvalidPolicy,"InvalidPolicy"},{Reason::WholeTrackRequired,"WholeTrackRequired"},
                {Reason::ProtectedBoundary,"ProtectedBoundary"},{Reason::RetiringOwner,"RetiringOwner"},
                {Reason::PositionUnavailable,"PositionUnavailable"},{Reason::LimitReached,"LimitReached"},
                {Reason::InputFailure,"InputFailure"},{Reason::ResourceBudget,"ResourceBudget"},
                {Reason::ResourceBusy,"ResourceBusy"},{Reason::InvalidArgument,"InvalidArgument"},
                {Reason::EngineFailure,"EngineFailure"}
            }};
            for (std::size_t i=0;i<reasons.size();++i)
                need(unsigned(reasons[i].first)==i && std::string_view(contract::name(reasons[i].first))==reasons[i].second,
                     "安定理由コードの値・名称が変化");
            need(std::string_view(contract::name(static_cast<Reason>(21)))=="Unknown" &&
                 std::string_view(contract::name(static_cast<Reason>(65535)))=="Unknown",
                 "未知理由を既知の成功へ変換");
            const contract::SeekReceipt seek{73,true,"legacy"};
            const contract::LoopReceipt loop{74,true,"legacy"};
            need(seek.id==73 && seek.accepted && seek.reason=="legacy" && seek.code==Reason::Available &&
                 loop.id==74 && loop.accepted && loop.reason=="legacy" && loop.code==Reason::Available,
                 "旧3フィールドreceipt初期化の互換性");
            using Code=contract::LoopSpeedReceiptCode;
            constexpr std::array<Code,11> codes{Code::Accepted,Code::Duplicate,Code::DuplicateInitial,
                Code::InvalidContext,Code::StaleContext,Code::NoInput,Code::NoLoop,Code::ClearPending,
                Code::LimitReached,Code::Busy,Code::Stopped};
            for (std::size_t i=0;i<codes.size();++i)
                need(unsigned(codes[i])==i, "既存Loop速度receiptコードの番号が変化");
            report.pass("D4.stable_reasons_and_legacy_receipts",reasons.size()+codes.size()+3);
        }
        {
            std::size_t cases=0;
            for (const auto& row : truth) for (unsigned other=0;other<4;++other) {
                const auto p=options((other&1)?Policy::Research:Policy::Disabled,
                                     (other&2)?Policy::Research:Policy::Disabled,row.policy);
                const auto f=contract::resolveFeatures(p,{true,true,row.approved,true});
                need(f.extraReservationBytes()==(row.effective?loopReservation:0),
                     "Exact/Interactive/現在周期承認から余分なLoop予約を導出");
                ++cases;
            }
            need(cases==24, "設定別予約検査の不足");
            report.pass("D5.reservation_configuration_derivation",cases);
        }
        {
            const contract::Capabilities c;
            struct Boundary {std::uint64_t bytes,frames,expected;};
            const std::array<Boundary,5> valid{{
                {1,1,256*mib+4097},
                {1,1024,256*mib+4097},
                {1,1025,256*mib+8193},
                {1024,48000,256*mib+1024+47*4096},
                {c.maxInputBytes,c.maxInputFrames,256*mib+c.maxInputBytes+28125ULL*4096}
            }};
            for (const auto& row : valid)
                need(contract::reservationBytes(row.bytes,row.frames)==row.expected,
                     "基礎予約の入力・1024境界の計算が不一致");
            const std::array<std::pair<std::uint64_t,std::uint64_t>,6> invalid{{
                {0,1},{1,0},{c.maxInputBytes+1,1},{1,c.maxInputFrames+1},
                {std::numeric_limits<std::uint64_t>::max(),1},
                {1,std::numeric_limits<std::uint64_t>::max()}
            }};
            for (const auto& row : invalid)
                rejects<std::length_error>([&] { (void)contract::reservationBytes(row.first,row.second); },
                                           "入力予約の上限・0を受理");
            need(valid.back().expected+loopReservation<=1024*mib,
                 "Loop追加分を含む最大既存予約が1GiBを超過");
            report.pass("D5.reservation_input_boundaries",valid.size()+invalid.size()+1);
        }
        {
            std::size_t cases=0;
            for (const auto& row : truth) {
                auto f=contract::resolveFeatures(options(Policy::Disabled,Policy::Disabled,row.policy),
                                                 {false,false,row.approved,false});
                const auto reserved=f.extraReservationBytes();
                for (const auto& state : runtime) {
                    contract::updateRuntime(f.nativeLoops,state.hasInput,state.validState,state.failed);
                    runtimeValue(f.nativeLoops,row,state);
                    need(f.extraReservationBytes()==reserved &&
                         reserved==(row.effective?loopReservation:0),
                         "NoInput/Preparing相当/Failedで必要予約をallowedから消した");
                    ++cases;
                }
            }
            need(cases==60, "runtimeと予約独立性の検査不足");
            report.pass("D5.reservation_runtime_independence",cases);
        }
        need(report.passed==checkIDs.size(), "必須IDが完了していない");
        std::cout << "{\"record\":\"summary\",\"status\":\"PASS\",\"run_complete\":true,"
                  << "\"expected\":" << checkIDs.size() << ",\"executed\":" << report.passed
                  << ",\"policy_approval_combinations\":432,\"runtime_cases\":60,\"legacy_cases\":4,"
                  << "\"audio\":false,\"engine_created\":false}\n";
        std::cout << "PROGRESSIVE_ADOPTION_CONTRACT_COMPLETE expected=" << checkIDs.size()
                  << " executed=" << report.passed << " passed=" << report.passed
                  << " audio=false engine_created=false\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Progressive採用契約: " << error.what() << '\n';
        std::cout << "{\"record\":\"summary\",\"status\":\"FAIL\",\"run_complete\":false,"
                  << "\"expected\":" << checkIDs.size() << ",\"executed\":" << report.passed
                  << ",\"audio\":false,\"engine_created\":false}\n";
        return 1;
    }
}
