// オフラインの供給・座標・固定RAW自己反復の検査。独立DSP参照ではない。
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase59Diagnostics.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
namespace p58=ts::prototype::phase58;
namespace p59=ts::prototype::phase59;
namespace fs=std::filesystem;
using Pipeline=p58::RealtimePipeline;
using State=p58::LoopTransitionState;
void need(bool v,const std::string& why){if(!v)throw std::runtime_error(why);}
std::string quote(const std::string& s){std::string r="\"";for(unsigned char c:s){if(c=='\"'||c=='\\'){r+='\\';r+=char(c);}else if(c=='\n')r+="\\n";else if(c<32)r+='?';else r+=char(c);}return r+'\"';}
std::string sha(const fs::path& path){std::ifstream f(path,std::ios::binary);need(bool(f),"SHA input missing");ts::prototype::Phase45PcmDigest d;std::array<char,65536> block{};while(f.read(block.data(),block.size())||f.gcount())d.update(block.data(),std::size_t(f.gcount()));need(f.eof(),"SHA read failed");return d.finish();}
const char* stateName(State s){switch(s){case State::Idle:return "Idle";case State::Requested:return "Requested";case State::Applying:return "Applying";case State::Committed:return "Committed";case State::FixedBoundaryCommitted:return "FixedBoundaryCommitted";case State::Cancelled:return "Cancelled";case State::Rejected:return "Rejected";}return "Unknown";}
template<class F>void wait(Pipeline& pipeline,F ready,const char* why){const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(120);while(!ready()){need(!pipeline.failed(),pipeline.diagnostics().error);need(std::chrono::steady_clock::now()<end,why);std::this_thread::sleep_for(std::chrono::microseconds(100));}}
bool terminal(const p58::LoopTransitionSnapshot& d){return d.state==State::Committed||d.state==State::FixedBoundaryCommitted;}
void ready(Pipeline& p){p.start();need(p.waitUntilReady(std::chrono::seconds(120)),"Ready timeout");need(!p.failed(),p.diagnostics().error);}
void writeMetrics(std::ostream& f,const p58::Diagnostics& d){const auto& m=d.loopReuse;f<<std::boolalpha<<"{\"session\":"<<d.session<<",\"input_generation\":"<<d.inputGeneration<<",\"final_data_available\":"<<d.finalDataAvailable<<",\"failed\":"<<d.failed<<",\"missing\":"<<d.missingFrames<<",\"rejected_writes\":"<<d.rejectedWrites<<",\"checkpoint_states\":"<<d.checkpointResidentStates<<",\"worker_creations\":"<<m.workerCreations<<",\"map_builds\":"<<m.mapBuilds<<",\"cache_bytes\":"<<m.cacheBytes<<",\"cache_read_frames\":"<<m.cacheReadFrames<<",\"seed_restores\":"<<m.seedRestores<<",\"seed_clones\":"<<m.seedClones<<",\"warm_fft_plans\":"<<m.warmFftPlanCreations<<",\"warm_discarded\":"<<m.warmDiscardedFrames<<",\"cold_discarded\":"<<m.coldDiscardedFrames<<",\"checkpoint_states_total\":"<<m.checkpointStates<<",\"checkpoint_peak_total\":"<<m.checkpointPeak<<",\"reconstruction_attempts\":"<<m.reconstructionAttempts<<",\"reconstructed_frames\":"<<m.reconstructedFrames<<",\"reconstruction_deferrals\":"<<m.reconstructionDeferrals<<",\"reconstruction_wall_s\":"<<m.reconstructionWallS<<",\"reconstruction_cpu_s\":"<<m.reconstructionCpuS<<",\"normal_preparation_code\":"<<int(m.normalPreparation)<<'}';}
struct Owners {
    std::unique_ptr<Pipeline> source,current,next;
    void retire(){for(auto* p:{source.get(),current.get(),next.get()})if(p){p->setRealtimeRendering(false);p->stop();}source.reset();current.reset();next.reset();}
    ~Owners(){try{retire();}catch(...){}}
};
struct Capture {
    std::size_t channels=0,frames=0,nonfinite=0,guardCompared=0,fixedCompared=0;
    std::vector<float> baseline,guard;
    std::size_t guardBegin=0;
    std::ofstream raw,spans,boundaries;
    std::array<std::array<float,4096>,2> pcm{};
    std::array<float,8192> interleaved{};
    Capture(const fs::path& out,std::size_t ch,std::size_t length):channels(ch),baseline(length*ch),raw(out/"current.f32",std::ios::binary),spans(out/"spans.csv"),boundaries(out/"boundaries.csv"){
        need(length&&length<=2000000,"separate host baseline exceeds 2M frames");guard.reserve(16384*ch);
        spans<<"role,session,input_generation,request_id,producer_cycle,map_version,cumulative_begin,cumulative_end,local_begin,local_end\n";
        boundaries<<"ordinal,role,session,source_cycle,cumulative_frame,local_B,next_local_A\n";
    }
    void protect(Pipeline& p,const fs::path& out){guardBegin=frames;const auto n=p.available();need(n<=16384,"FIFO protection snapshot exceeds product FIFO bound");std::array<float,2> value{};for(std::size_t i=0;i<n;++i){need(p.peekAudioFrame(i,value),"stable FIFO prefix peek failed");for(std::size_t c=0;c<channels;++c){need(std::isfinite(value[c]),"FIFO prefix NaN/Inf");guard.push_back(value[c]);}}std::ofstream f(out/"protected_prefix.f32",std::ios::binary);f.write(reinterpret_cast<const char*>(guard.data()),guard.size()*sizeof(float));need(bool(f),"protected prefix save failed");}
    void take(Pipeline& p,std::size_t n,std::size_t expectedAt,std::size_t fixedA,std::size_t fixedL,bool fixedExpected,std::uint64_t cycle,const p58::LoopTransitionSnapshot& d,std::uint64_t requestID){
        need(n&&n<=4096,"nonpositive/oversized span");wait(p,[&]{return p.available()>=n;},"offline FIFO supply timeout");
        float* pointers[]{pcm[0].data(),pcm[1].data()};const auto r=p.pullAudio(pointers,n);need(r.wanted==n&&r.received==n&&r.outputBefore==expectedAt,"missing/duplicate/wrong local PCM interval");
        const auto spanBegin=frames;
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<channels;++c){const auto v=pcm[c][i];if(!std::isfinite(v))++nonfinite;need(std::isfinite(v),"actual RAW NaN/Inf");
            const auto at=frames+i;interleaved[i*channels+c]=v;
            if(at<fixedL)baseline[at*channels+c]=v;
            else if(fixedExpected){need(std::bit_cast<std::uint32_t>(v)==std::bit_cast<std::uint32_t>(baseline[((expectedAt-fixedA+i)%fixedL)*channels+c]),"fixed RAW self-repeat differs");++fixedCompared;}
            if(at>=guardBegin&&at-guardBegin<guard.size()/channels){need(std::bit_cast<std::uint32_t>(v)==std::bit_cast<std::uint32_t>(guard[(at-guardBegin)*channels+c]),"published FIFO prefix was overwritten/reordered");++guardCompared;}
        }
        raw.write(reinterpret_cast<const char*>(interleaved.data()),n*channels*sizeof(float));need(bool(raw),"RAW write failed");frames+=n;
        spans<<"current,"<<p.diagnostics().session<<','<<p.inputGeneration()<<','<<requestID<<','<<cycle<<','<<(terminal(d)?d.mapVersion:0)<<','<<spanBegin<<','<<frames<<','<<expectedAt<<','<<expectedAt+n<<'\n';
    }
};
int run(int argc,char** argv){
    fs::path out;bool owned=false;Owners owners;std::size_t captured=0;std::string failure;
    try{
        need(argc==14,"INPUT candidate|baseline NEW_OUT A B INITIAL TARGET WARM REQUEST_OFFSET CALLBACK any|cache|uncached dynamic|fixed|either EXPECTED_FIXED_L(0=any)");
        const fs::path input=fs::absolute(argv[1]);const std::string preset=argv[2],cacheExpected=argv[11],expectedState=argv[12];
        const std::size_t a=std::stoull(argv[4]),b=std::stoull(argv[5]),warm=std::stoull(argv[8]),offset=std::stoull(argv[9]),callback=std::stoull(argv[10]),requiredL=std::stoull(argv[13]);
        const auto initial=std::uint32_t(std::stoul(argv[6])),target=std::uint32_t(std::stoul(argv[7]));
        need((preset=="candidate"||preset=="baseline")&&(cacheExpected=="any"||cacheExpected=="cache"||cacheExpected=="uncached")&&(expectedState=="dynamic"||expectedState=="fixed"||expectedState=="either"),"invalid preset/expectation");
        need(p59::formalSpeed(initial)&&p59::formalSpeed(target)&&initial!=target&&warm>=2&&warm<=8&&(callback==64||callback==128||callback==512||callback==4096),"speed/warm/callback condition");
        ts::WavStreamReader wav(input);need(wav.channels()>=1&&wav.channels()<=2&&a<b&&b<=wav.frames(),"fixture/range");
        need(b-a>=wav.sampleRate()/10,"requires >=100ms input loop");
        out=fs::weakly_canonical(fs::absolute(argv[3]));const auto relative=out.lexically_relative(fs::canonical("build"));
        need(!relative.empty()&&!relative.is_absolute()&&*relative.begin()!="..","output must be inside ignored build/ (run from repository root)");
        need(!fs::exists(out)&&fs::create_directories(out),"fresh output required");owned=true;
        const auto inputSha=sha(input),binarySha=sha(fs::absolute(argv[0]));
        {std::ofstream f(out/"EXPECTED.json");f<<"{\"suite\":\"phase62_cache_focus\",\"expected\":1,\"input_sha256\":"<<quote(inputSha)<<",\"binary_sha256\":"<<quote(binarySha)<<",\"input_A\":"<<a<<",\"input_B\":"<<b<<",\"initial\":"<<initial<<",\"target\":"<<target<<",\"preset\":"<<quote(preset)<<",\"warm\":"<<warm<<",\"request_offset\":"<<offset<<",\"callback_partition\":"<<callback<<",\"cache_expectation\":"<<quote(cacheExpected)<<",\"terminal_expectation\":"<<quote(expectedState)<<",\"required_fixed_L\":"<<requiredL<<",\"independent_DSP\":false,\"realtime\":false}\n";}
        p58::Configuration config;config.speedMicros=initial;config.candidate=preset=="candidate";config.verifyPcm=false;config.residentInput=true;config.scheduling=p58::WorkerScheduling::AudioWorkgroup;
        owners.source=std::make_unique<Pipeline>(input,config);ready(*owners.source);wait(*owners.source,[&]{return owners.source->finalAnalysisAvailable();},"analysis timeout");
        owners.current=owners.source->createLoopSeek(a,b,initial);owners.current->enableLoopReuse(a);
        // 最初のsourceを破棄してから第二の実行所有者を作る。瞬間的な第三所有者も作らない。
        owners.source->stop();owners.source.reset();ready(*owners.current);
        const auto oa=owners.current->loopOutputStartFrame(),ob=owners.current->loopOutputEndFrame(),length=ob-oa;
        need(ob>oa&&length>=512&&length<=2000000&&offset<length,"fixed L/request offset bounds");need(!requiredL||length==requiredL,"actual Map L does not realize requested cache-boundary fixture");
        const auto before=owners.current->diagnostics();const bool cache=before.loopReuse.cacheBytes>0;
        need(cacheExpected=="any"||(cacheExpected=="cache")==cache,"cache classification differs from actual product Map/range");
        owners.next=owners.current->createLoopSeek(a,b,target);owners.next->enableLoopReuse(a);ready(*owners.next);
        const auto na=owners.next->loopOutputStartFrame(),nb=owners.next->loopOutputEndFrame(),nextLength=nb-na;need(nb>na&&nextLength>=512&&nextLength<=2000000,"next fixed period outside host/product bounds");need(owners.next->inputGeneration()==owners.current->inputGeneration(),"input lease identity mismatch");
        need(Pipeline::executionOwnerCounts().alive==2&&Pipeline::executionOwnerCounts().peak<=2,"preparation owner cap violated");
        need(owners.current->setRealtimeRendering(true)&&owners.next->setRealtimeRendering(true),"offline rendering arm failed");
        Capture capture(out,wav.channels(),length);const auto requestAt=warm*length+offset;
        bool requested=false,committed=false;std::uint64_t requestID=0,boundaryCount=0;std::size_t requestPrefixFrames=0,terminalEnd=0;
        p58::LoopTransitionSnapshot descriptor;const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(180);
        while(!committed||capture.frames<terminalEnd){
            need(std::chrono::steady_clock::now()<deadline&&capture.frames<8000000,"finite terminal/capture bound exceeded");need(!owners.current->failed(),owners.current->diagnostics().error);
            if(!requested&&capture.frames==requestAt){need(owners.current->loopReadCycle()==warm,"request consumer cycle mismatch");
                {std::ofstream f(out/"BEFORE_REQUEST.json");f<<"{\"consumer_cycle\":"<<owners.current->loopReadCycle()<<",\"consumer_cumulative\":"<<capture.frames<<",\"requested_local\":"<<oa+offset<<",\"metrics\":";writeMetrics(f,owners.current->diagnostics());f<<"}\n";}
                capture.protect(*owners.current,out);requestPrefixFrames=capture.guard.size()/wav.channels();need(requestPrefixFrames>0,"no published FIFO prefix to protect");const auto receipt=owners.current->requestLoopTransition(target,oa+offset);need(receipt.result==ts::prototype::Phase39RequestResult::Accepted&&receipt.id,"request not Accepted");requestID=receipt.id;requested=true;
                // Offline driver: retain this consumer frontier until the normal
                // planner and producer settle. No callback is gated or running.
                wait(*owners.current,[&]{return terminal(owners.current->loopTransition());},"offline request decision timeout");}
            descriptor=owners.current->loopTransition();
            if(terminal(descriptor)){
                need(requested&&descriptor.operationID==requestID&&descriptor.auditSequence>0,"terminal identity/sequence");need(descriptor.cycle>=warm&&descriptor.cycle<warm+64,"unbounded/retrograde terminal cycle");
                need(descriptor.localStart==oa&&descriptor.localEnd>oa&&descriptor.cumulativeStart==descriptor.cycle*length&&descriptor.cumulativeEnd-descriptor.cumulativeStart==descriptor.localEnd-oa,"terminal local/cumulative coordinates");
                need(descriptor.fifoReadAtCommit<=descriptor.fifoWriteAtCommit&&descriptor.fifoWriteAtCommit==descriptor.cumulativeStart+descriptor.publishedAtCommit-descriptor.localStart,"same-sample W protection equation");
                need(descriptor.pcmGeneratedAtCommit>=descriptor.pendingPcmFramesAtCommit&&descriptor.pcmGeneratedAtCommit-descriptor.pendingPcmFramesAtCommit==descriptor.publishedAtCommit,"same-sample P-pending protection equation");
                need(descriptor.publishedAtCommit>=descriptor.localStart&&descriptor.fifoWriteAtCommit<=descriptor.cumulativeEnd&&descriptor.pendingPcmFramesAtCommit<=descriptor.cumulativeEnd-descriptor.fifoWriteAtCommit&&descriptor.cumulativeEnd>=capture.frames,"invalid terminal publication/end range");
                if(descriptor.state==State::FixedBoundaryCommitted){need(descriptor.localEnd==ob&&descriptor.reason!=p58::LoopTransitionReason::None,"fixed terminal changed B or lost deferral reason");}
                else need(descriptor.generatedAtCommit==descriptor.pcmGeneratedAtCommit&&descriptor.reason==p58::LoopTransitionReason::None,"dynamic P/reason mismatch");
                need(expectedState=="either"||(expectedState=="dynamic"&&descriptor.state==State::Committed)||(expectedState=="fixed"&&descriptor.state==State::FixedBoundaryCommitted),"actual terminal differs from planned contract");
                terminalEnd=descriptor.cumulativeEnd;committed=true;
            }
            need(descriptor.state!=State::Cancelled,"unexpected cancellation");
            if(committed&&capture.frames==terminalEnd)break;
            std::size_t local=oa+capture.frames%length,end=ob;std::uint64_t cycle=capture.frames/length;
            if(committed&&capture.frames>=descriptor.cumulativeStart){local=descriptor.localStart+capture.frames-descriptor.cumulativeStart;end=descriptor.localEnd;cycle=descriptor.cycle;}
            auto count=std::min<std::size_t>(callback,end-local);if(!requested)count=std::min(count,requestAt-capture.frames);
            const bool fixedExpected=!requested||(committed&&descriptor.state==State::FixedBoundaryCommitted);
            capture.take(*owners.current,count,local,oa,length,fixedExpected,cycle,descriptor,requestID);captured=capture.frames;
            if(local+count==end){++boundaryCount;capture.boundaries<<boundaryCount<<",current,"<<before.session<<','<<cycle<<','<<capture.frames<<','<<end<<','<<(committed&&capture.frames==terminalEnd?na:oa)<<'\n';}
        }
        need(capture.guardCompared==requestPrefixFrames*wav.channels(),"published prefix did not survive through actual consumption");
        wait(*owners.current,[&]{return owners.current->finished();},"finite current producer did not finish");
        wait(*owners.current,[&]{return owners.current->loopCommittedTimeMap().has_value();},"terminal acknowledged Map unavailable");
        const auto map=owners.current->loopCommittedTimeMap();need(map.has_value(),"committed Map lost before retire");
        {std::ofstream f(out/"product_map.nodes.bin",std::ios::binary);f.write(reinterpret_cast<const char*>(map->starts().data()),map->starts().size()*sizeof(long long));need(bool(f),"Map save failed");}
        if(b<wav.frames())need(std::size_t(std::llround(map->outputPositionForInputSample(double(b))))==descriptor.localEnd,"product Map(B) differs from terminal B");
        need(owners.current->setRealtimeRendering(false),"current disarm");owners.current->stop();const auto currentFinal=owners.current->diagnostics();
        if(b==wav.frames())need(currentFinal.outputFrames==descriptor.localEnd,"whole-input B differs from final output length");
        const auto ops=owners.current->speedOperations();p59::exportOperations(out,ops,initial);
        const auto operation=std::find_if(ops.begin(),ops.end(),[&](const auto& op){return op.id==requestID;});need(operation!=ops.end()&&operation->acceptedLogicalPresented==oa+offset,"accepted request identity/coordinate lost");
        if(descriptor.state==State::Committed)need(operation->appliedS>=0&&operation->completedS>=0&&operation->change.plan.completionOutputSample<static_cast<long long>(descriptor.localEnd),"dynamic change did not complete before B");
        else need(operation->appliedS<0,"fixed boundary fallback was actually dynamically applied");
        {std::ofstream f(out/"OPERATION.json");f<<"{\"request_id\":"<<operation->id<<",\"session\":"<<operation->session<<",\"input_generation\":"<<operation->inputGeneration<<",\"accepted_logical_presented\":"<<operation->acceptedLogicalPresented<<",\"planner_logical_presented\":"<<operation->logicalPresented<<",\"target\":"<<operation->target<<",\"state\":"<<quote(p59::name(operation->state))<<",\"applied_s\":"<<operation->appliedS<<",\"completed_s\":"<<operation->completedS<<"}\n";}
        owners.current.reset();need(Pipeline::executionOwnerCounts().alive==1,"old execution owner not retired");
        capture.raw.close();need(bool(capture.raw),"current RAW close");
        // 次固定所有者は要求前からReady。自然Bに相当する輸送境界でのみ読取り先を替える。
        // 実callback/mixerの境界補正はこの低レベル試験の対象外。
        std::vector<float> nextFirst(nextLength*wav.channels());need(nextLength<=2000000,"separate next baseline bound");std::ofstream nextRaw(out/"next.f32",std::ios::binary);std::size_t nextFrames=0,nextCompared=0;
        while(nextFrames<nextLength*2){const auto local=na+nextFrames%nextLength;const auto count=std::min<std::size_t>(callback,nb-local);wait(*owners.next,[&]{return owners.next->available()>=count;},"next FIFO timeout");float* pointers[]{capture.pcm[0].data(),capture.pcm[1].data()};const auto r=owners.next->pullAudio(pointers,count);need(r.wanted==count&&r.received==count&&r.outputBefore==local,"next RAW gap/duplicate/local position");
            for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<wav.channels();++c){const auto value=capture.pcm[c][i];need(std::isfinite(value),"next RAW NaN/Inf");capture.interleaved[i*wav.channels()+c]=value;const auto at=(local-na+i)*wav.channels()+c;if(nextFrames<nextLength)nextFirst[at]=value;else{need(std::bit_cast<std::uint32_t>(value)==std::bit_cast<std::uint32_t>(nextFirst[at]),"next fixed RAW self-repeat differs");++nextCompared;}}
            nextRaw.write(reinterpret_cast<const char*>(capture.interleaved.data()),count*wav.channels()*sizeof(float));need(bool(nextRaw),"next RAW write failed");capture.spans<<"next,"<<owners.next->diagnostics().session<<','<<owners.next->inputGeneration()<<','<<requestID<<','<<nextFrames/nextLength<<",0,"<<terminalEnd+nextFrames<<','<<terminalEnd+nextFrames+count<<','<<local<<','<<local+count<<'\n';nextFrames+=count;
            if(local+count==nb){++boundaryCount;capture.boundaries<<boundaryCount<<",next,"<<owners.next->diagnostics().session<<','<<nextFrames/nextLength-1<<','<<terminalEnd+nextFrames<<','<<nb<<','<<na<<'\n';}
        }
        nextRaw.close();need(bool(nextRaw),"next RAW close");need(owners.next->setRealtimeRendering(false),"next disarm");owners.next->stop();const auto nextFinal=owners.next->diagnostics();
        for(const auto* d:{&currentFinal,&nextFinal}){need(d->finalDataAvailable&&!d->failed&&!d->missingFrames&&!d->rejectedWrites,"joined supply/final stats failure");need(d->checkpointResidentStates<=2&&d->loopReuse.checkpointStates<=2&&d->loopReuse.checkpointPeak<=2&&d->loopReuse.workerCreations==2&&d->loopReuse.warmFftPlanCreations==0&&d->loopReuse.seedClones==1,"checkpoint/worker/FFT/seed regression");}
        need(currentFinal.loopReuse.workerCreations==before.loopReuse.workerCreations,"dynamic preparation created new source workers");
        if(cache&&descriptor.state==State::Committed)need(currentFinal.loopReuse.cacheReadFrames>0&&currentFinal.loopReuse.reconstructionAttempts>0&&currentFinal.loopReuse.seedRestores>before.loopReuse.seedRestores,"cache reconstructed without same-DSP seed restore evidence");
        owners.next.reset();const auto counts=Pipeline::executionOwnerCounts();need(counts.alive==0&&counts.peak<=2,"whole-lifetime owner cap/retirement");need(sha(input)==inputSha&&sha(fs::absolute(argv[0]))==binarySha,"input/binary changed during run");
        capture.spans.close();capture.boundaries.close();
        {std::ofstream f(out/"METRICS.json");f<<"{\"before\":";writeMetrics(f,before);f<<",\"current_final\":";writeMetrics(f,currentFinal);f<<",\"next_final\":";writeMetrics(f,nextFinal);f<<"}\n";}
        {std::ofstream f(out/"COMMIT.json");f<<std::boolalpha<<"{\"state\":"<<quote(stateName(descriptor.state))<<",\"operation_id\":"<<descriptor.operationID<<",\"producer_cycle\":"<<descriptor.cycle<<",\"map_version\":"<<descriptor.mapVersion<<",\"local_start\":"<<descriptor.localStart<<",\"local_end\":"<<descriptor.localEnd<<",\"cumulative_start\":"<<descriptor.cumulativeStart<<",\"cumulative_end\":"<<descriptor.cumulativeEnd<<",\"generated_at_commit\":"<<descriptor.generatedAtCommit<<",\"published_at_commit\":"<<descriptor.publishedAtCommit<<",\"fifo_read_at_commit\":"<<descriptor.fifoReadAtCommit<<",\"fifo_write_at_commit\":"<<descriptor.fifoWriteAtCommit<<",\"pending_pcm_frames\":"<<descriptor.pendingPcmFramesAtCommit<<",\"pcm_generated\":"<<descriptor.pcmGeneratedAtCommit<<",\"cache_backed\":"<<descriptor.cacheBackedAtCommit<<",\"reason_code\":"<<int(descriptor.reason)<<",\"audit_sequence\":"<<descriptor.auditSequence<<"}\n";}
        std::ofstream f(out/"SUMMARY.json");f<<"{\"schema\":2,\"run_complete\":true,\"suite\":\"phase62_cache_focus\",\"expected\":1,\"executed\":1,\"status\":\"PASS\",\"terminal_state\":"<<quote(stateName(descriptor.state))<<",\"fixed_L\":"<<length<<",\"next_L\":"<<nextLength<<",\"request_cycle\":"<<warm<<",\"request_cumulative\":"<<requestAt<<",\"terminal_cycle\":"<<descriptor.cycle<<",\"current_frames\":"<<capture.frames<<",\"next_frames\":"<<nextFrames<<",\"independent_Sigma_L\":false,\"emitted_Sigma_L\":"<<terminalEnd+nextFrames<<",\"published_prefix_frames_compared\":"<<capture.guardCompared/wav.channels()<<",\"fixed_self_repeat_samples_compared\":"<<capture.fixedCompared+nextCompared<<",\"owner_peak\":"<<counts.peak<<",\"owners_after_stop\":"<<counts.alive<<",\"checkpoint_states_max\":"<<std::max(currentFinal.loopReuse.checkpointPeak,nextFinal.loopReuse.checkpointPeak)<<",\"current_raw_sha256\":"<<quote(sha(out/"current.f32"))<<",\"next_raw_sha256\":"<<quote(sha(out/"next.f32"))<<",\"nonfinite\":0,\"missing\":0,\"independent_DSP\":false,\"independent_planner\":false,\"independent_PCM\":false,\"callback_allocation\":\"NOT_RUN\",\"boundary_correction\":\"NOT_RUN\",\"realtime\":false,\"local_overall_go\":false}\n";f.close();std::ifstream final(out/"SUMMARY.json");std::cout<<final.rdbuf();return 0;
    }catch(const std::exception& error){failure=error.what();try{owners.retire();}catch(const std::exception& cleanup){failure+="; cleanup: ";failure+=cleanup.what();}if(owned){const auto counts=Pipeline::executionOwnerCounts();std::ofstream f(out/"SUMMARY.json");f<<"{\"suite\":\"phase62_cache_focus\",\"expected\":1,\"executed\":0,\"status\":\"FAIL\",\"captured_frames\":"<<captured<<",\"reason\":"<<quote(failure)<<",\"owner_peak\":"<<counts.peak<<",\"owners_after_cleanup\":"<<counts.alive<<",\"independent_DSP\":false,\"realtime\":false}\n";}std::cerr<<failure<<'\n';return 2;}
}
}
int main(int argc,char** argv){return run(argc,argv);}
