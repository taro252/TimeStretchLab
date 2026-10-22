// オフライン制御回帰。音声装置/callback/Workgroup昇格は使用しない。
// 初回A保存状態の再結合と資源上限だけを検査する。
// 任意の凍結全曲RAWを渡した場合だけ、独立DSP/独立OA/OBとの完全一致も検査する。
// CMake登録と実行はA1の固定ソース監査終了後に行う。
#include "prototype/Phase58RealtimePipeline.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
namespace p58 = ts::prototype::phase58;
using Pipeline = p58::RealtimePipeline;
using Owner = std::unique_ptr<Pipeline>;
using Clock = std::chrono::steady_clock;

void need(bool value, const std::string& why) {
    if (!value) throw std::runtime_error(why);
}
template<class Predicate> void wait(Pipeline& pipeline, Predicate predicate, const char* why) {
    const auto deadline = Clock::now() + std::chrono::seconds(120);
    while (!predicate()) {
        const auto d = pipeline.diagnostics();
        need(!d.failed, d.error);
        need(Clock::now() < deadline, why);
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
}
void bounded(const Pipeline& pipeline) {
    const auto d = pipeline.diagnostics();
    need(d.loopReuse.checkpointStates <= 2 && d.loopReuse.checkpointPeak <= 2,
         "同一leaseの完全checkpointが2個を超えた");
    const auto owners = Pipeline::executionOwnerCounts();
    need(owners.alive <= 2 && owners.peak <= 2, "実行ownerが瞬間的に2個を超えた");
    need(!d.failed && !d.missingFrames && !d.rejectedWrites, "オフライン供給が失敗した");
}
void ready(Pipeline& pipeline) {
    pipeline.start();
    need(pipeline.waitUntilReady(std::chrono::seconds(120)), "Ready待機が失敗した: " + pipeline.diagnostics().error);
    bounded(pipeline);
}
void retire(Owner& owner) {
    if (!owner) return;
    owner->stop();
    const auto d = owner->diagnostics();
    need(d.finalDataAvailable && !d.failed && !d.missingFrames && !d.rejectedWrites,
         "stop/join後の最終監査が不正");
    bounded(*owner);
    owner.reset();
}

// 第2ownerを実際にReadyまで動かす間、旧FIFOを維持する。3番目は作らない。
void replace(Owner& current, Owner next) {
    need(current && next, "置換ownerがない");
    const auto oldConsumed = current->diagnostics().consumed;
    const auto guardCount = std::min<std::size_t>(current->available(), 32);
    std::array<std::array<float, 2>, 32> guard{};
    for (std::size_t i = 0; i < guardCount; ++i)
        need(current->peekAudioFrame(i, guard[i]), "旧FIFO保護用peekが失敗");
    ready(*next);
    need(Pipeline::executionOwnerCounts().alive == 2, "準備中のowner数が2ではない");
    need(current->diagnostics().consumed == oldConsumed, "新準備が旧FIFOを消費した");
    for (std::size_t i = 0; i < guardCount; ++i) {
        std::array<float, 2> actual{};
        need(current->peekAudioFrame(i, actual), "新準備が旧FIFOを失った");
        for (std::size_t ch = 0; ch < current->channels(); ++ch)
            need(std::bit_cast<std::uint32_t>(actual[ch]) == std::bit_cast<std::uint32_t>(guard[i][ch]),
                 "新準備が旧FIFOのbit/順序を変更した");
    }
    retire(current);
    current = std::move(next);
    bounded(*current);
}

struct SavedRange {
    std::size_t a = 0, b = 0, oa = 0, ob = 0;
    std::vector<float> firstPeriod;
};
struct IndependentReference {
    std::string path;
    std::array<std::array<std::size_t, 2>, 3> bounds{};
    bool supplied() const { return !path.empty(); }
    void compare(const SavedRange& range, std::size_t channels, std::size_t index) const {
        if (!supplied()) return;
        need(bounds[index][0] == range.oa && bounds[index][1] == range.ob,
             "OA/OBが凍結参照の独立Mapと一致しない");
        std::ifstream stream(path, std::ios::binary);
        need(bool(stream), "独立固定参照RAWがない");
        stream.seekg(std::streamoff(range.oa * channels * sizeof(float)));
        std::vector<float> expected(range.firstPeriod.size());
        need(bool(stream.read(reinterpret_cast<char*>(expected.data()),
                              std::streamsize(expected.size() * sizeof(float)))), "独立RAWの指定区間が不足");
        for (std::size_t i = 0; i < expected.size(); ++i)
            need(std::isfinite(expected[i]) &&
                 std::bit_cast<std::uint32_t>(expected[i]) == std::bit_cast<std::uint32_t>(range.firstPeriod[i]),
                 "初回RAWが凍結固定Exactの全bit/全chと一致しない");
    }
};

// 音声callbackを使わず、唯一のconsumerとして有限FIFOを読む。
SavedRange collect(Pipeline& pipeline, std::size_t a, std::size_t b) {
    SavedRange range{a, b, pipeline.loopOutputStartFrame(), pipeline.loopOutputEndFrame(), {}};
    const auto period = range.ob - range.oa, channels = pipeline.channels();
    need(range.ob > range.oa && period >= 512 && period <= 1000000, "試験範囲が有界でない");
    range.firstPeriod.resize(period * channels);
    std::array<std::array<float, 4096>, 2> pcm{};
    float* pointers[]{pcm[0].data(), pcm[1].data()};
    const auto total = period * 3 + 17;
    std::size_t cursor = 0;
    while (cursor < total) {
        const auto n = std::min<std::size_t>(4096, total - cursor);
        wait(pipeline, [&]{ return pipeline.available() >= n; }, "RAW供給待機が期限超過");
        const auto rendered = pipeline.pullAudio(pointers, n);
        need(rendered.wanted == n && rendered.received == n &&
             rendered.outputBefore == range.oa + cursor % period, "RAW欠落/重複/絶対出力座標が不正");
        for (std::size_t i = 0; i < n; ++i) for (std::size_t ch = 0; ch < channels; ++ch) {
            const auto value = pcm[ch][i];
            const auto at = cursor + i;
            need(std::isfinite(value), "RAWにNaN/Inf");
            if (at < period) range.firstPeriod[at * channels + ch] = value;
            else need(std::bit_cast<std::uint32_t>(value) ==
                      std::bit_cast<std::uint32_t>(range.firstPeriod[(at % period) * channels + ch]),
                      "3周期のRAWに欠落/重複/位相差がある");
        }
        cursor += n;
    }
    need(pipeline.loopReadCycle() == 3, "17フレームの部分周期を余分な完了周回に数えた");
    bounded(pipeline);
    return range;
}

void samePcm(const SavedRange& expected, const SavedRange& actual) {
    need(expected.a == actual.a && expected.b == actual.b && expected.oa == actual.oa &&
         expected.ob == actual.ob && expected.firstPeriod.size() == actual.firstPeriod.size(),
         "cold/warmの入力・絶対出力範囲または全ch長が違う");
    for (std::size_t i = 0; i < expected.firstPeriod.size(); ++i)
        need(std::bit_cast<std::uint32_t>(expected.firstPeriod[i]) ==
             std::bit_cast<std::uint32_t>(actual.firstPeriod[i]), "cold/warmの全RAW bitが違う");
}

Owner loop(Pipeline& current, std::size_t a, std::size_t b, std::uint32_t speed) {
    auto result = current.createLoopSeek(a, b, speed);
    result->enableLoopReuse(a);
    return result;
}
void initialResult(Pipeline& pipeline, bool expectedHit, const char* id) {
    const auto d = pipeline.diagnostics();
    // 新診断の配置が異なる場合、この参照だけ実装へ合わせる。
    need(d.loopReuse.initialCheckpointHit == expectedHit, std::string(id) + ": 初回checkpoint hit判定が違う");
    const auto oa = pipeline.loopOutputStartFrame();
    need(d.checkpointStartFrame <= oa && d.checkpointStartFrame + d.loopReuse.coldDiscardedFrames == oa,
         std::string(id) + ": 省略した保存位置と実際の前置破棄数の和がAと違う");
    need(expectedHit ? d.loopReuse.coldDiscardedFrames < 2048 : d.checkpointStartFrame == 0,
         std::string(id) + ": warm前置が有界でない/不整合状態を使用した");
    const auto consumed = d.consumed;
    const auto cycle = pipeline.loopReadCycle();
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
    need(pipeline.diagnostics().consumed == consumed && pipeline.loopReadCycle() == cycle,
         "Readyの準備だけで消費/周回が進んだ");
    bounded(pipeline);
    std::cout << "{\"case\":\"" << id << "\",\"status\":\"PASS\",\"hit\":" << expectedHit
              << ",\"OA\":" << oa << ",\"checkpoint_start\":" << d.checkpointStartFrame
              << ",\"cold_discarded\":" << d.loopReuse.coldDiscardedFrames
              << ",\"checkpoint_peak\":" << d.loopReuse.checkpointPeak << "}\n";
}

Owner source(const char* input, p58::Configuration config) {
    auto owner = std::make_unique<Pipeline>(input, config);
    ready(*owner);
    wait(*owner, [&]{ return owner->finalAnalysisAvailable(); }, "最終解析が未完了");
    return owner;
}

void roundTrip(const char* input, p58::Configuration config, std::size_t a, std::size_t b,
               const char* label, const IndependentReference& reference, std::size_t referenceIndex) {
    auto current = source(input, config);
    const auto generation = current->inputGeneration();
    replace(current, loop(*current, a, b, 1000000));
    initialResult(*current, false, (std::string(label) + "_fresh_cold").c_str());
    const auto cold = collect(*current, a, b);
    const auto coldReuse = current->diagnostics().loopReuse;
    need(referenceIndex == 2 ? cold.ob - cold.oa > 96000 && coldReuse.cacheBytes == 0
                             : cold.ob - cold.oa <= 96000 && coldReuse.cacheBytes > 0,
         "独立検査用の短RAW/96000超非cache条件を実際に通らなかった");
    reference.compare(cold, current->channels(), referenceIndex);

    // Clearのオフライン相当。通常Exact B継続を別ownerでReadyにしてから旧Loopを退役。
    // nativeの境界加工/Paused Clear台帳の試験は別途行い、ここでは代用しない。
    replace(current, current->createSeek(b, 1000000));
    need(current->inputGeneration() == generation, "Clear相当で入力leaseが変わった");
    if (config.seekCheckpoints)
        need(current->diagnostics().checkpointResidentStates > 0,
             "任意の通常seek checkpointとの2枠競合を実際に作れなかった");
    else need(current->diagnostics().checkpointResidentStates == 0,
              "Loop最適化が通常seek checkpointを暗黙に有効化した");
    bounded(*current);
    replace(current, loop(*current, a, b, 1000000));
    initialResult(*current, true, (std::string(label) + "_clear_re_request_hit").c_str());
    const auto warm = collect(*current, a, b);
    samePcm(cold, warm);
    reference.compare(warm, current->channels(), referenceIndex);
    retire(current);
    need(Pipeline::executionOwnerCounts().alive == 0, "roundTrip後にownerが残った");
}

void incompatibilities(const char* input, p58::Configuration config, std::size_t a, std::size_t b) {
    auto current = source(input, config);
    replace(current, loop(*current, a, b, 1000000));
    initialResult(*current, false, "invalidate_setup_cold");
    replace(current, loop(*current, a, b, 1250000));
    initialResult(*current, false, "speed_mismatch_cold");
    replace(current, loop(*current, a + 1, b, 1250000));
    initialResult(*current, false, "A_mismatch_cold");
    replace(current, loop(*current, a + 1, b + 1, 1250000));
    initialResult(*current, false, "B_mismatch_cold");
    const auto oldGeneration = current->inputGeneration();
    auto fresh = std::make_unique<Pipeline>(input, config);
    replace(current, std::move(fresh));
    wait(*current, [&]{ return current->finalAnalysisAvailable(); }, "別lease最終解析が未完了");
    need(current->inputGeneration() != oldGeneration, "同じ入力パスの再prepareが別generationでない");
    replace(current, loop(*current, a + 1, b + 1, 1250000));
    initialResult(*current, false, "new_input_lease_generation_cold");
    config.candidate = !config.candidate;
    const auto beforePresetGeneration = current->inputGeneration();
    replace(current, std::make_unique<Pipeline>(input, config));
    wait(*current, [&]{ return current->finalAnalysisAvailable(); }, "別preset最終解析が未完了");
    need(current->inputGeneration() != beforePresetGeneration, "別preset新prepareが旧leaseを再利用した");
    replace(current, loop(*current, a + 1, b + 1, 1250000));
    initialResult(*current, false, "new_preset_new_lease_cold");
    // 同じleaseのpreset変更APIはない。内部setterを増やさず、上の新prepareだけを証明する。
    std::cout << "{\"case\":\"same_lease_preset_mutation\",\"status\":\"NOT_EXERCISED\","
                 "\"reason\":\"公開factoryはpresetを継承するため新leaseでのみ変更可能\"}\n";
    retire(current);
}
} // namespace

int main(int argc, char** argv) {
    try {
        need(argc == 3 || argc == 10,
             "INPUT.wav baseline|candidate [FROZEN_FIXED_1000000_RAW OA0 OB0 OA1 OB1 OAlong OBlong]");
        const std::string preset = argv[2];
        need(preset == "baseline" || preset == "candidate", "presetが不正");
        ts::WavStreamReader input(argv[1]);
        const auto rate = input.sampleRate();
        need(input.frames() >= rate * 5ULL, "5秒以上の小さな人工入力を指定してください");
        p58::Configuration config;
        config.speedMicros = 1000000;
        config.candidate = preset == "candidate";
        config.verifyPcm = false;
        config.residentInput = true;
        config.seekCheckpoints = false; // Loop専用cacheと通常seek opt-inを分離する。
        config.boundedEpochReservations = true;
        IndependentReference reference;
        if (argc == 10) {
            reference.path = argv[3];
            for (std::size_t i = 0; i < 3; ++i)
                reference.bounds[i] = {std::stoull(argv[4 + i * 2]), std::stoull(argv[5 + i * 2])};
        }
        const auto a = std::size_t(rate) + 17;
        const auto shortEnd = a + rate / 10;
        const auto longEnd = a + std::size_t(rate) * 3 + 1;
        need(longEnd + 1 < input.frames(), "長区間とB継続の入力余裕が不足");
        roundTrip(argv[1], config, 0, rate / 10, "A0_short", reference, 0);
        roundTrip(argv[1], config, a, shortEnd, "nonzero_short", reference, 1);
        roundTrip(argv[1], config, a, longEnd, "nonzero_uncached", reference, 2);
        auto withSeekCheckpoints = config;
        withSeekCheckpoints.seekCheckpoints = true;
        roundTrip(argv[1], withSeekCheckpoints, a, shortEnd, "normal_checkpoint_slot_competition", reference, 1);
        incompatibilities(argv[1], config, a, shortEnd);
        const auto owners = Pipeline::executionOwnerCounts();
        need(!owners.alive && owners.peak <= 2, "最終退役または最大owner数が不正");
        std::cout << "{\"status\":\"PASS\",\"suite\":\"initial_loop_checkpoint_offline\","
                     "\"independent_fixed_raw_supplied\":" << reference.supplied()
                  << ",\"audio_callbacks_used\":false,\"owner_peak\":" << owners.peak
                  << ",\"owner_alive\":" << owners.alive
                  << ",\"native_playing_paused_clear\":\"NOT_ASSESSED\",\"realtime_deadlines\":\"NOT_ASSESSED\"}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
