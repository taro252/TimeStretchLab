// 入力監視だけのオフライン回帰。音声装置・callback・Workgroup昇格は使わない。
// INPUT.wav NEW_OUTPUT [dynamic|standard]。5状態×5変更＋新generation復帰。
// chmodのmetadata検出と、実UIDに対するopen権限拒否を別々に記録する。
#include "prototype/Phase58RealtimePipeline.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
namespace p58 = ts::prototype::phase58;
namespace fs = std::filesystem;
using Pipeline = p58::RealtimePipeline;
using Clock = std::chrono::steady_clock;
using Owner = std::unique_ptr<Pipeline>;
void need(bool ok, const std::string& why) { if (!ok) throw std::runtime_error(why); }
std::uint64_t nowNs() {
    return std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count());
}
std::string quote(const std::string& text) {
    std::string result = "\"";
    for (unsigned char c : text) {
        if (c == '"' || c == '\\') { result += '\\'; result += char(c); }
        else if (c == '\n') result += "\\n";
        else if (c == '\r') result += "\\r";
        else if (c == '\t') result += "\\t";
        else if (c < 32) result += '?';
        else result += char(c);
    }
    return result + '"';
}
template<class Predicate> void wait(Pipeline& pipeline, Predicate predicate, const char* why) {
    const auto end = Clock::now() + std::chrono::seconds(30);
    while (!predicate()) {
        need(!pipeline.failed(), pipeline.diagnostics().error);
        need(Clock::now() < end, why);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
void ready(Pipeline& pipeline) {
    pipeline.start();
    need(pipeline.waitUntilReady(std::chrono::seconds(30)), "Readyに到達しない: " + pipeline.diagnostics().error);
}
void finalAnalysis(Pipeline& pipeline) {
    wait(pipeline, [&]{ return pipeline.finalAnalysisAvailable() && pipeline.diagnostics().analysisDone; }, "確定解析が未完了");
}

// 例外時も全ownerを先にjoinしてからFDを閉じ、chmodを復元する。
struct CaseOwners {
    fs::path path;
    mode_t originalMode = 0600;
    int heldFd = -1;
    std::vector<Owner> owners;
    explicit CaseOwners(fs::path p) : path(std::move(p)) {}
    void stopAll() {
        for (auto& owner : owners) if (owner) owner->stop();
    }
    ~CaseOwners() {
        try { stopAll(); } catch (...) {}
        owners.clear();
        if (heldFd >= 0) close(heldFd);
        if (fs::exists(path)) chmod(path.c_str(), originalMode);
    }
};
struct Observation {
    std::string id, state, mutation, status = "FAIL", reason;
    bool analysisComplete = false, permissionOpenDenied = false, chmodAttempted = false;
    int permissionErrno = 0;
    std::uint64_t generation = 0, mutationBeginNs = 0, mutationEndNs = 0;
    std::uint64_t idleCalls = 0, validationCallsBefore = 0, validationCallsAfter = 0;
    double validationCpuDeltaS = 0, validationWallDeltaS = 0;
    std::vector<double> detectionSeconds;
    std::size_t owners = 0;
};

std::uint32_t little32(const unsigned char* p) {
    return std::uint32_t(p[0]) | (std::uint32_t(p[1]) << 8) |
           (std::uint32_t(p[2]) << 16) | (std::uint32_t(p[3]) << 24);
}
std::size_t dataOffset(const fs::path& input) {
    std::ifstream stream(input, std::ios::binary);
    std::array<unsigned char, 12> header{};
    need(bool(stream.read(reinterpret_cast<char*>(header.data()), header.size())), "WAV headerが短い");
    need(std::string(reinterpret_cast<char*>(header.data()), 4) == "RIFF" &&
         std::string(reinterpret_cast<char*>(header.data() + 8), 4) == "WAVE", "RIFF WAVが必要");
    std::array<unsigned char, 8> chunk{};
    while (stream.read(reinterpret_cast<char*>(chunk.data()), chunk.size())) {
        const auto bytes = little32(chunk.data() + 4);
        if (std::string(reinterpret_cast<char*>(chunk.data()), 4) == "data") {
            need(bytes > 0, "空のWAV data");
            return std::size_t(stream.tellg()) + std::min<std::size_t>(bytes - 1, 256);
        }
        stream.seekg(std::streamoff(bytes) + (bytes & 1), std::ios::cur);
    }
    throw std::runtime_error("WAV data chunkがない");
}

Observation one(const fs::path& input, const fs::path& output, p58::Configuration config,
                const std::string& state, const std::string& mutation, std::size_t mutationOffset) {
    Observation result;
    result.id = state + "_" + mutation; result.state = state; result.mutation = mutation;
    try {
        const auto folder = output / result.id;
        need(fs::create_directory(folder), "一意なfixture folderを作れない");
        const auto selected = folder / "selected.wav";
        need(fs::copy_file(input, selected), "fixture複製に失敗");
        need(chmod(selected.c_str(), 0600) == 0, "一意コピーを試験UIDだけの読み書きへ設定できない");
        const auto replacement = folder / "replacement.wav";
        if (mutation == "replace") need(fs::copy_file(input, replacement), "置換fixtureを複製できない");
        CaseOwners resources(selected);
        struct stat original{};
        need(stat(selected.c_str(), &original) == 0, "元fixture statが失敗");
        resources.originalMode = original.st_mode & 0777;
        resources.heldFd = open(selected.c_str(), O_RDWR | O_CLOEXEC);
        need(resources.heldFd >= 0, "fixture用保持FDを開けない");
        resources.owners.push_back(std::make_unique<Pipeline>(selected, config));
        ready(*resources.owners.front());
        auto* source = resources.owners.front().get();
        result.generation = source->inputGeneration();
        if (state != "ready") finalAnalysis(*source);
        if (state == "paused_equivalent") {
            std::array<std::array<float, 512>, 2> buffer{};
            float* pointers[]{buffer[0].data(), buffer[1].data()};
            need(source->available() >= 512 && source->pullAudio(pointers, 512).received == 512,
                 "Paused相当の実消費位置を作れない");
        } else if (state == "two_owners" || state == "eof_seek") {
            const auto at = state == "eof_seek" ? source->inputFrames() : source->inputFrames() / 2;
            auto next = source->createSeek(at, config.speedMicros);
            ready(*next);
            need(next->inputGeneration() == result.generation, "seekが同leaseでない");
            if (state == "eof_seek") {
                source->stop();
                need(source->diagnostics().finalDataAvailable, "旧sourceがjoinされていない");
                resources.owners.clear();
                resources.owners.push_back(std::move(next));
                need(resources.owners.front()->finished() && resources.owners.front()->available() == 0,
                     "EOF seekの空suffix条件を実際に通っていない");
            } else resources.owners.push_back(std::move(next));
        }
        result.owners = resources.owners.size();
        const auto ownerCounts = Pipeline::executionOwnerCounts();
        need(ownerCounts.alive == result.owners && ownerCounts.peak <= 2, "owner上限2が破られた");
        auto& first = *resources.owners.front();
        const auto beforeIdle = first.diagnostics();
        need(beforeIdle.controlCostsMeasured, "通常制御診断が有効でない");
        std::vector<std::size_t> consumed;
        for (auto& owner : resources.owners) consumed.push_back(owner->diagnostics().consumed);
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        for (std::size_t i = 0; i < resources.owners.size(); ++i)
            need(!resources.owners[i]->failed() && resources.owners[i]->diagnostics().consumed == consumed[i],
                 "静止中に失敗または入力消費が起きた");
        const auto before = first.diagnostics();
        need(before.inputValidationCost.calls >= beforeIdle.inputValidationCost.calls,
             "静止中に元入力検査counterが後退した");
        // この50msは呼出回数の観測だけ。特定のpoll周期や重複削減率を合格条件にしない。
        result.analysisComplete = before.analysisDone;
        result.idleCalls = before.inputValidationCost.calls - beforeIdle.inputValidationCost.calls;
        result.validationCallsBefore = before.inputValidationCost.calls;

        // 全caseは新規コピーだけを変更する。利用者の元INPUTには書き込まない。
        result.mutationBeginNs = nowNs();
        if (mutation == "delete") need(fs::remove(selected), "選択パス削除が失敗");
        else if (mutation == "replace") {
            fs::rename(replacement, selected);
        } else if (mutation == "rename") fs::rename(selected, folder / "renamed.wav");
        else if (mutation == "chmod") {
            need(chmod(selected.c_str(), 0000) == 0, "chmod 0000が失敗");
            result.chmodAttempted = true;
            errno = 0;
            const int probe = open(selected.c_str(), O_RDONLY | O_CLOEXEC);
            result.permissionErrno = probe >= 0 ? 0 : errno;
            result.permissionOpenDenied = probe < 0 && (errno == EACCES || errno == EPERM);
            if (probe >= 0) close(probe);
        } else if (mutation == "held_fd_content") {
            unsigned char byte = 0;
            need(pread(resources.heldFd, &byte, 1, off_t(mutationOffset)) == 1, "保持FDから元byteを読めない");
            byte ^= 1;
            need(pwrite(resources.heldFd, &byte, 1, off_t(mutationOffset)) == 1 && fsync(resources.heldFd) == 0,
                 "保持FD経由の内容変更が失敗");
        } else throw std::runtime_error("未定義mutation");
        result.mutationEndNs = nowNs();
        result.detectionSeconds.assign(resources.owners.size(), -1.);
        const auto deadlineNs = result.mutationBeginNs + 3000000000ULL;
        while (std::find(result.detectionSeconds.begin(), result.detectionSeconds.end(), -1.) != result.detectionSeconds.end()) {
            for (std::size_t i = 0; i < resources.owners.size(); ++i)
                if (result.detectionSeconds[i] < 0 && resources.owners[i]->failed())
                    result.detectionSeconds[i] = double(nowNs() - result.mutationBeginNs) * 1e-9;
            need(nowNs() <= deadlineNs, "既存の3秒以内入力失敗条件を満たさない");
            if (std::find(result.detectionSeconds.begin(), result.detectionSeconds.end(), -1.) != result.detectionSeconds.end())
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        for (std::size_t i = 0; i < resources.owners.size(); ++i) {
            auto& owner = *resources.owners[i];
            need(owner.diagnostics().failed && !owner.diagnostics().error.empty(), "入力喪失が無理由のEOSになった");
            std::array<std::array<float, 32>, 2> buffer{};
            float* pointers[]{buffer[0].data(), buffer[1].data()};
            const auto pulled = owner.pullAudio(pointers, 32);
            need(!pulled.wanted && !pulled.received && owner.diagnostics().consumed == consumed[i],
                 "入力失敗後にPCM消費/復活が起きた");
        }
        resources.stopAll();
        const auto after = first.diagnostics();
        result.validationCallsAfter = after.inputValidationCost.calls;
        result.validationCpuDeltaS = after.inputValidationCost.cpuS - before.inputValidationCost.cpuS;
        result.validationWallDeltaS = after.inputValidationCost.wallS - before.inputValidationCost.wallS;
        need(result.validationCallsAfter > result.validationCallsBefore && result.validationCpuDeltaS >= 0 &&
             result.validationWallDeltaS >= 0, "入力検査の累積診断が後退/欠落");
        for (auto& owner : resources.owners) {
            const auto d = owner->diagnostics();
            need(d.finalDataAvailable && d.failed && !d.scheduling.active && d.scheduling.joins == d.scheduling.leaves &&
                 d.scheduling.leaves == d.scheduling.restores, "failure後の最終join/退役が不完全");
            // validation counterはInput共有の累積値である。2owner分を加算しない。
            need(d.inputValidationCost.calls == after.inputValidationCost.calls, "同lease検査診断が別々になった");
        }
        result.status = "PASS";
    } catch (const std::exception& error) { result.reason = error.what(); }
    return result;
}

void write(std::ostream& stream, const Observation& r) {
    stream << std::setprecision(12) << "{\"id\":" << quote(r.id) << ",\"status\":" << quote(r.status)
           << ",\"reason\":" << quote(r.reason) << ",\"input_generation\":" << r.generation
           << ",\"owners\":" << r.owners << ",\"analysis_complete_before_mutation\":" << r.analysisComplete
           << ",\"mutation_begin_steady_ns\":" << r.mutationBeginNs << ",\"mutation_end_steady_ns\":" << r.mutationEndNs
           << ",\"detection_seconds\":[";
    for (std::size_t i = 0; i < r.detectionSeconds.size(); ++i) { if (i) stream << ','; stream << r.detectionSeconds[i]; }
    stream << "],\"idle_50ms_validation_calls\":" << r.idleCalls << ",\"validation_calls_before\":" << r.validationCallsBefore
           << ",\"validation_calls_after\":" << r.validationCallsAfter << ",\"validation_cpu_delta_s\":" << r.validationCpuDeltaS
           << ",\"validation_wall_delta_s\":" << r.validationWallDeltaS
           << ",\"validation_scope\":\"input lease shared; do not sum owners\",\"duplicate_check_reduction\":\"NOT_ASSESSED\""
           << ",\"chmod_attempted\":" << r.chmodAttempted << ",\"permission_open_denied\":" << r.permissionOpenDenied
           << ",\"permission_probe_errno\":" << r.permissionErrno << ",\"permission_loss_status\":"
           << quote(!r.chmodAttempted ? "NOT_APPLICABLE" : r.permissionOpenDenied ? "EXERCISED" : "NOT_EXERCISED_UID_ACCESS_ALLOWED")
           << "}\n";
}
} // namespace

int main(int argc, char** argv) {
    try {
        need(argc == 3 || argc == 4, "INPUT.wav NEW_OUTPUT [dynamic|standard]");
        const fs::path input = fs::absolute(argv[1]), output = fs::absolute(argv[2]);
        const std::string mode = argc == 4 ? argv[3] : "dynamic";
        need(mode == "dynamic" || mode == "standard", "modeが不正");
        ts::WavStreamReader info(input);
        need(info.frames() >= 1024 && info.frames() <= std::size_t(info.sampleRate()) * 12 && fs::file_size(input) < 16000000,
             "12秒/16MB以内の小さい新規コピー用WAVが必要");
        need(!fs::exists(output) && fs::create_directories(output), "新規output directoryが必要");
        p58::Configuration config;
        config.speedMicros = 1000000; config.verifyPcm = false; config.residentInput = true;
        config.measureControlCosts = true; config.seekCheckpoints = false; config.boundedEpochReservations = true;
        if (mode == "dynamic") { config.dynamicTransitions = true; config.scheduling = p58::WorkerScheduling::AudioWorkgroup; }
        const std::array<std::string, 5> states{"ready", "final_analysis", "paused_equivalent", "eof_seek", "two_owners"};
        const std::array<std::string, 5> mutations{"delete", "replace", "rename", "chmod", "held_fd_content"};
        std::vector<std::string> ids;
        for (const auto& state : states) for (const auto& mutation : mutations) ids.push_back(state + "_" + mutation);
        ids.push_back("new_generation_recovery");
        std::ofstream expected(output / "EXPECTED.json");
        expected << "{\"suite\":\"phase62_input_watch_offline\",\"expected\":" << ids.size()
                 << ",\"mode\":" << quote(mode) << ",\"uid\":" << getuid() << ",\"euid\":" << geteuid()
                 << ",\"maximum_detection_s\":3,\"audio_callback_used\":false,\"workgroup_promoted\":false,\"expected_IDs\":[";
        for (std::size_t i = 0; i < ids.size(); ++i) { if (i) expected << ','; expected << quote(ids[i]); }
        expected << "]}\n"; expected.close(); need(bool(expected), "EXPECTED保存が失敗");
        const auto offset = dataOffset(input);
        std::ofstream records(output / "checks.jsonl");
        std::size_t passed = 0, executed = 0, permissionCases = 0, permissionDenied = 0;
        std::set<std::uint64_t> generations;
        for (const auto& state : states) for (const auto& mutation : mutations) {
            const auto row = one(input, output, config, state, mutation, offset);
            write(records, row); records.flush(); ++executed; passed += row.status == "PASS";
            if (row.generation) generations.insert(row.generation);
            permissionCases += row.chmodAttempted; permissionDenied += row.permissionOpenDenied;
            need(Pipeline::executionOwnerCounts().alive == 0, "case終了後にownerが残った");
        }
        Observation recovered; recovered.id = "new_generation_recovery";
        try {
            const auto copy = output / "recovery_unique.wav";
            need(fs::copy_file(input, copy), "復帰fixture複製が失敗");
            auto owner = std::make_unique<Pipeline>(copy, config); ready(*owner); finalAnalysis(*owner);
            recovered.generation = owner->inputGeneration();
            need(!generations.count(recovered.generation) && !owner->failed(), "別prepareのgenerationが復帰しない");
            owner->stop(); need(owner->diagnostics().finalDataAvailable, "復帰ownerのjoinが未完了"); owner.reset();
            recovered.status = "PASS";
        } catch (const std::exception& error) { recovered.reason = error.what(); }
        write(records, recovered); ++executed; passed += recovered.status == "PASS";
        records.close(); need(bool(records), "check保存が失敗");
        const auto owners = Pipeline::executionOwnerCounts();
        const bool ok = executed == ids.size() && passed == ids.size() && !owners.alive && owners.peak <= 2;
        std::ofstream summary(output / "SUMMARY.json");
        summary << "{\"suite\":\"phase62_input_watch_offline\",\"status\":" << quote(ok ? "PASS" : "FAIL")
                << ",\"run_complete\":true,\"expected\":" << ids.size() << ",\"executed\":" << executed << ",\"passed\":" << passed
                << ",\"owner_peak\":" << owners.peak << ",\"owners_alive\":" << owners.alive
                << ",\"chmod_cases\":" << permissionCases << ",\"permission_open_denial_exercised\":" << permissionDenied
                << ",\"permission_loss_detection_status\":" << quote(permissionDenied == permissionCases && permissionCases == 5 ? "EXERCISED" : "PARTIAL_NOT_EXERCISED")
                << ",\"paused_scope\":\"offline consumed then stationary; native Pause is not exercised\""
                << ",\"duplicate_check_reduction\":\"NOT_ASSESSED\",\"input_fixtures\":\"new unique copies only; original INPUT unchanged\""
                << ",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"public_go\":false}\n";
        summary.close(); need(bool(summary), "SUMMARY保存が失敗");
        std::cout << "input-watch " << mode << " " << passed << '/' << ids.size() << " permission-denied "
                  << permissionDenied << '/' << permissionCases << '\n';
        return ok ? 0 : 1;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}
