// Offline cycle-0 RAW test. The frozen executable independently replans at
// the measured frontier; its DSP does not link the modified product libraries.
// Build and run only after the LoopTransition protocol is implemented.
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase59Diagnostics.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <spawn.h>
#include <stdexcept>
#include <string>
#include <sys/wait.h>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <unistd.h>

extern char** environ;
using ts::prototype::phase58::Configuration;
using ts::prototype::phase58::RealtimePipeline;
namespace phase59 = ts::prototype::phase59;
namespace fs = std::filesystem;

namespace {
constexpr const char* capturedSha = "1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818";
constexpr const char* baseline = "bb22efcbd27f999e8ffe85bbe3f03e20895be3f2";
void require(bool value, const std::string& reason) {
    if (!value) throw std::runtime_error(reason);
}
template<class Predicate> void waitFor(Predicate predicate, const char* stage) {
    const auto deadline = std::chrono::steady_clock::now()+std::chrono::seconds(120);
    while (!predicate()) {
        require(std::chrono::steady_clock::now()<deadline, std::string(stage)+" timeout");
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
}
std::string quote(const std::string& value) {
    std::string result="\"";
    for (unsigned char c:value) {
        if (c=='"'||c=='\\') {result+='\\';result+=char(c);}
        else if (c=='\n') result+="\\n";
        else if (c=='\r') result+="\\r";
        else if (c=='\t') result+="\\t";
        else if (c<32) {constexpr char hex[]="0123456789abcdef";result+="\\u00";result+=hex[c>>4];result+=hex[c&15];}
        else result+=char(c);
    }
    return result+'"';
}
std::string fileSha(const fs::path& path) {
    std::ifstream input(path,std::ios::binary);
    require(bool(input),"SHA input missing: "+path.string());
    ts::prototype::Phase45PcmDigest digest;
    std::array<char,65536> block{};
    while (input.read(block.data(),block.size())||input.gcount())
        digest.update(block.data(),std::size_t(input.gcount()));
    require(input.eof(),"SHA read failed: "+path.string());
    return digest.finish();
}
int runFrozen(const std::vector<std::string>& command,const fs::path& log) {
    const int fd=::open(log.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);
    require(fd>=0,"fresh oracle log required");
    posix_spawn_file_actions_t actions;
    int code=posix_spawn_file_actions_init(&actions);
    if (code) {::close(fd);throw std::runtime_error("spawn action init");}
    code=posix_spawn_file_actions_adddup2(&actions,fd,STDOUT_FILENO);
    if (!code) code=posix_spawn_file_actions_adddup2(&actions,fd,STDERR_FILENO);
    if (!code) code=posix_spawn_file_actions_addclose(&actions,fd);
    std::vector<char*> arguments;
    for (const auto& part:command) arguments.push_back(const_cast<char*>(part.c_str()));
    arguments.push_back(nullptr);
    pid_t pid=0;
    if (!code) code=posix_spawn(&pid,command.front().c_str(),&actions,nullptr,arguments.data(),environ);
    posix_spawn_file_actions_destroy(&actions);::close(fd);
    require(!code,"frozen reference launch failed: "+std::to_string(code));
    int status=0;
    while (::waitpid(pid,&status,0)<0) require(errno==EINTR,"oracle waitpid failed");
    return WIFEXITED(status)?WEXITSTATUS(status):128+(WIFSIGNALED(status)?WTERMSIG(status):0);
}
void equalFiles(const fs::path& actual,const fs::path& expected,std::size_t channels,
                bool pcm,const fs::path& mismatch) {
    require(fs::file_size(actual)==fs::file_size(expected),"independent reference frame/node count differs");
    const auto bytes=fs::file_size(actual);
    require(bytes&&bytes%(pcm?channels*sizeof(float):sizeof(long long))==0,"invalid RAW/node byte count");
    std::ifstream a(actual,std::ios::binary),b(expected,std::ios::binary);
    std::array<char,65536> av{},bv{};std::size_t offset=0;
    while (a.read(av.data(),av.size())||a.gcount()) {
        const auto count=std::size_t(a.gcount());b.read(bv.data(),count);
        require(std::size_t(b.gcount())==count,"independent reference truncated");
        if (pcm) for (std::size_t i=0;i<count;i+=sizeof(float)) {
            float af=0,bf=0;std::memcpy(&af,av.data()+i,4);std::memcpy(&bf,bv.data()+i,4);
            require(std::isfinite(af)&&std::isfinite(bf),"NaN/Inf in actual or independent RAW");
        }
        if (std::memcmp(av.data(),bv.data(),count)!=0) {
            std::size_t first=0;while(first<count&&av[first]==bv[first])++first;
            std::ofstream evidence(mismatch);
            evidence<<"{\"status\":\"FAIL\",\"byte\":"<<offset+first;
            if (pcm) {
                const auto within=first/4*4;std::uint32_t ab=0,bb=0;
                std::memcpy(&ab,av.data()+within,4);std::memcpy(&bb,bv.data()+within,4);
                const auto sample=(offset+within)/4;
                evidence<<",\"frame\":"<<sample/channels<<",\"channel\":"<<sample%channels
                        <<",\"actual_bits\":"<<ab<<",\"reference_bits\":"<<bb;
            }
            evidence<<"}\n";
            throw std::runtime_error(pcm?"independent dynamic RAW bits differ":"independent planner Map nodes differ");
        }
        offset+=count;
    }
    require(offset==bytes,"comparison incomplete");
}
}

int main(int argc,char** argv) {
    fs::path out;
    bool evidenceOwned=false;
    std::size_t captured=0;int oracleExit=-1;
    try {
        require(argc==7||argc==8,"input.wav initial_micros target_micros candidate|baseline NEW_OUTPUT_DIR captured_reference [request_at_output]");
        const fs::path input=fs::absolute(argv[1]),oracle=fs::absolute(argv[6]);
        const auto initial=std::uint32_t(std::stoul(argv[2])),target=std::uint32_t(std::stoul(argv[3]));
        const std::string preset=argv[4];const bool candidate=preset=="candidate";
        require(candidate||preset=="baseline","invalid preset");
        require(phase59::formalSpeed(initial)&&phase59::formalSpeed(target)&&initial!=target,"distinct formal speeds required");
        const auto requestAt=argc==8?std::stoull(argv[7]):8192ULL;
        require(requestAt>=2048,"request must follow observable initial RAW");
        out=fs::absolute(argv[5]);require(!fs::exists(out),"new evidence directory required");fs::create_directories(out);evidenceOwned=true;
        const auto oracleHash=fileSha(oracle);require(oracleHash==capturedSha,"frozen captured_reference SHA mismatch");
        ts::WavStreamReader wav(input);
        const auto fixedEnd=std::size_t(std::llround(wav.frames()/(initial/1000000.)));
        require(fixedEnd>96000&&requestAt+32768<fixedEnd,"long cycle with legal future interval required");
        std::ofstream manifest(out/"EXPECTED.json");
        manifest<<"{\"suite\":\"phase62_dynamic_pcm\",\"expected\":1,\"initial_micros\":"<<initial
                <<",\"target_micros\":"<<target<<",\"preset\":"<<quote(preset)<<",\"input_A\":0,\"input_B\":"<<wav.frames()
                <<",\"request_at_output\":"<<requestAt<<",\"input_sha256\":"<<quote(fileSha(input))
                <<",\"binary_sha256\":"<<quote(fileSha(fs::absolute(argv[0])))<<",\"reference_sha256\":"<<quote(oracleHash)
                <<",\"reference_baseline\":"<<quote(baseline)<<",\"comparison\":\"frozen planner at measured frontier, complete committed Map and cycle-0 Float32 RAW bits; finite separately\",\"realtime\":false}\n";
        manifest.close();
        Configuration config;config.speedMicros=initial;config.candidate=candidate;config.residentInput=true;config.verifyPcm=false;
        config.scheduling=ts::prototype::phase58::WorkerScheduling::AudioWorkgroup;
        auto source=std::make_unique<RealtimePipeline>(input,config);source->start();
        require(source->waitUntilReady(std::chrono::seconds(120)),"source Ready failed");
        waitFor([&]{require(!source->failed(),"source failed");return source->finalAnalysisAvailable();},"final analysis");
        auto loop=source->createLoopSeek(0,wav.frames(),initial);loop->enableLoopReuse(0);
        source->stop();source.reset();loop->start();
        require(loop->waitUntilReady(std::chrono::seconds(120)),"loop Ready failed");
        require(loop->loopOutputStartFrame()==0&&loop->loopOutputEndFrame()==fixedEnd,"initial cycle coordinates");
        require(!loop->diagnostics().loopReuse.cacheBytes,"test requires uncached current DSP state");
        require(loop->setRealtimeRendering(true),"rendering arm failed");
        using TransitionState=decltype(loop->loopTransition().state);
        auto transition=loop->loopTransition();
        phase59::RequestReceipt receipt;
        bool requested=false,committed=false;
        std::size_t end=fixedEnd;
        std::ofstream raw(out/"actual.f32",std::ios::binary);
        std::array<std::array<float,512>,2> pcm{};float* pointers[]{pcm[0].data(),pcm[1].data()};
        std::array<float,1024> interleaved{};
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);
        while (captured<end) {
            require(std::chrono::steady_clock::now()<deadline,"current cycle capture timeout");
            require(!loop->failed(),"dynamic loop worker failure: "+loop->diagnostics().error);
            if (!requested&&captured==requestAt) {
                receipt=loop->requestLoopTransition(target,captured);
                require(receipt.result==ts::prototype::Phase39RequestResult::Accepted&&receipt.id,"dynamic loop request rejected");
                requested=true;
                // This is a logical off-line consumer, not an audio callback.
                // Keep its declared request cursor while the ordinary planner
                // and producer finish their transaction. Native asynchronous
                // frontier behaviour is measured by the separate host.
                waitFor([&]{const auto s=loop->loopTransition().state;return s==TransitionState::Committed||s==TransitionState::Rejected||s==TransitionState::Cancelled;},"off-line dynamic transaction");
            }
            transition=loop->loopTransition();
            if(transition.state==TransitionState::Rejected||transition.state==TransitionState::Cancelled){
                loop->setRealtimeRendering(false);loop->stop();phase59::exportOperations(out,loop->speedOperations(),initial);
                throw std::runtime_error("dynamic request rejected/cancelled");
            }
            if (transition.state==TransitionState::Committed) {
                require(transition.cycle==0&&transition.operationID==receipt.id,"request changed cycle/identity");
                require(transition.localStart==0&&transition.cumulativeStart==0,"cycle-0 coordinates shifted");
                require(transition.localEnd==transition.cumulativeEnd&&transition.localEnd>captured,"dynamic B already consumed");
                require(transition.generatedAtCommit>=transition.publishedAtCommit,"pending PCM interval inverted");
                end=transition.localEnd;committed=true;
            }
            auto count=std::min<std::size_t>(512,end-captured);
            if (!requested) count=std::min<std::size_t>(count,requestAt-captured);
            if (loop->available()<count) {std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
            const auto result=loop->pullAudio(pointers,count);
            require(result.received==count&&result.outputBefore==captured,"RAW gap/duplicate/epoch position");
            for (std::size_t i=0;i<count;++i) for (std::size_t c=0;c<wav.channels();++c) {
                require(std::isfinite(pcm[c][i]),"nonfinite product RAW");interleaved[i*wav.channels()+c]=pcm[c][i];
            }
            raw.write(reinterpret_cast<const char*>(interleaved.data()),count*wav.channels()*sizeof(float));captured+=count;
        }
        raw.close();require(bool(raw)&&requested&&committed,"dynamic cycle did not commit before B");
        require(loop->setRealtimeRendering(false),"rendering disarm failed");loop->stop();
        const auto diagnostic=loop->diagnostics();
        require(diagnostic.finalDataAvailable&&!diagnostic.failed&&!diagnostic.missingFrames&&!diagnostic.rejectedWrites,"joined pipeline failure/missing RAW");
        require(diagnostic.loopReuse.workerCreations==2&&diagnostic.loopReuse.warmFftPlanCreations==0,"dynamic handoff recreated workers/FFT plans");
        const auto operations=loop->speedOperations();
        const auto found=std::find_if(operations.begin(),operations.end(),[&](const auto& op){return op.id==receipt.id;});
        require(found!=operations.end()&&found->appliedS>=0&&found->target==target&&found->planningDecided,"missing applied operation");
        require(found->logicalPresented==requestAt&&found->change.plan.appliedOutputSample>0&&
                std::size_t(found->change.plan.completionOutputSample)<end,"transition did not finish in current cycle");
        require(found->frontier.preparedOutput>=found->publishedAtPlan&&found->publishedAtPlan%2048==0,
                "frozen replay needs actual engine publication frontier, including pending RAW");
        phase59::exportOperations(out,operations,initial);
        const auto map=loop->dynamicTimeMap();
        require(std::size_t(std::llround(map.outputPositionForInputSample(double(wav.frames()))))==end,"dynamic B differs from committed Map");
        std::ofstream nodes(out/"dynamic_map.nodes.bin",std::ios::binary);
        nodes.write(reinterpret_cast<const char*>(map.starts().data()),map.starts().size()*sizeof(long long));nodes.close();
        loop.reset(); // All product DSP/FD owners have retired before old DSP runs.
        const std::vector<std::string> command{oracle.string(),input.string(),std::to_string(initial),preset,out.string(),(out/"reference.f32").string(),(out/"reference").string()};
        std::ofstream invocation(out/"REFERENCE_COMMAND.json");invocation<<"[";
        for (std::size_t i=0;i<command.size();++i) invocation<<(i?",":"")<<quote(command[i]);invocation<<"]\n";invocation.close();
        oracleExit=runFrozen(command,out/"reference.log");require(!oracleExit,"independent planner/frontier/DSP replay failed");
        require(fs::is_regular_file(out/"reference.json")&&fs::is_regular_file(out/"reference.plans.csv"),"reference final statistics missing");
        equalFiles(out/"actual.f32",out/"reference.f32",wav.channels(),true,out/"first_pcm_mismatch.json");
        equalFiles(out/"dynamic_map.nodes.bin",out/"reference.nodes.bin",wav.channels(),false,out/"first_map_mismatch.json");
        require(fs::file_size(out/"reference.f32")==end*wav.channels()*sizeof(float),"independent dynamic B/length mismatch");
        const auto actualHash=fileSha(out/"actual.f32"),referenceHash=fileSha(out/"reference.f32");
        require(actualHash==referenceHash&&fileSha(oracle)==oracleHash,"PCM or frozen executable SHA changed");
        std::ofstream result(out/"SUMMARY.json");
        result<<"{\"suite\":\"phase62_dynamic_pcm\",\"expected\":1,\"executed\":1,\"status\":\"PASS\",\"cycle\":0,\"map_version\":"<<transition.mapVersion
              <<",\"operation_id\":"<<receipt.id<<",\"initial_micros\":"<<initial<<",\"target_micros\":"<<target
              <<",\"frames\":"<<captured<<",\"dynamic_B\":"<<end<<",\"generated_at_commit\":"<<transition.generatedAtCommit
              <<",\"published_at_commit\":"<<transition.publishedAtCommit<<",\"applied_output\":"<<found->change.plan.appliedOutputSample
              <<",\"completion_output\":"<<found->change.plan.completionOutputSample<<",\"independent_planner\":true,\"independent_DSP_RAW\":true,\"map_bit_exact\":true,\"nonfinite\":0,\"oracle_exit\":"<<oracleExit
              <<",\"pcm_sha256\":"<<quote(actualHash)<<",\"reference_sha256\":"<<quote(oracleHash)
              <<",\"realtime\":false,\"next_fixed_owner\":\"NOT_RUN\",\"final_boundary_processing\":\"NOT_RUN\"}\n";
        result.close();std::ifstream final(out/"SUMMARY.json");std::cout<<final.rdbuf();return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';
        if (evidenceOwned&&fs::is_directory(out)) {
            std::ofstream result(out/"SUMMARY.json");
            result<<"{\"suite\":\"phase62_dynamic_pcm\",\"expected\":1,\"executed\":0,\"status\":\"FAIL\",\"captured_frames\":"<<captured
                  <<",\"oracle_exit\":"<<oracleExit<<",\"reason\":"<<quote(error.what())<<",\"realtime\":false}\n";
        }
        return 1;
    }
}
