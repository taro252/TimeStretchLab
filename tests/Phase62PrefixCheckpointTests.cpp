// 通常seekの既存完全保存点 P<=OA と、Clearの固定A保存点によるExact prefix回帰。
// 音声装置・callback・Workgroup昇格を使わない。実行はrootが直列統括する。
// 凍結参照は先に別processで作成し、製品DSPから期待PCMを作らない。
// INPUT preset REF.f32 FROZEN_BINARY OA OBshort OBlong OAearly OBearly OB0 NEW_OUTPUT
// A=rate*8+31, Bshort=A+rate/10, Blong=A+rate*3+1,
// earlyA=rate/2+11, earlyB=earlyA+rate/10, A0=0, B0=rate/10。
// 例: phase61_frozen_reference INPUT 1000000 baseline REF.f32 A Bshort Blong earlyA earlyB 0 B0
// JSON positions[0,1,2,3,4,6]を、このhostの6座標引数へ渡す。
#define main included_phase62_initial_checkpoint_main
#if __has_include("Phase62InitialCheckpointTests.cpp")
#include "Phase62InitialCheckpointTests.cpp"
#else
#include "../../../tests/Phase62InitialCheckpointTests.cpp"
#endif
#undef main
#include "prototype/Phase45PcmDigest.h"
#include <iomanip>
#include <optional>
#include <set>

namespace {
constexpr const char* frozenSha="de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748";
std::string quoted(const std::string& text) {
    std::string result="\"";
    for(unsigned char c:text) {
        if(c=='"'||c=='\\'){result+='\\';result+=char(c);}
        else if(c=='\n')result+="\\n";
        else if(c=='\r')result+="\\r";
        else if(c=='\t')result+="\\t";
        else result+=c<32?'?':char(c);
    }
    return result+'"';
}
std::string fileSha(const std::filesystem::path& path) {
    std::ifstream stream(path,std::ios::binary);need(bool(stream),"SHA入力がない: "+path.string());
    ts::prototype::Phase45PcmDigest digest;std::array<char,65536> block{};
    while(stream.read(block.data(),block.size())||stream.gcount())digest.update(block.data(),std::size_t(stream.gcount()));
    need(stream.eof(),"SHA読取失敗");return digest.finish();
}
struct Audit {
    std::filesystem::path output;
    std::vector<std::string> ids;
    std::set<std::string> passed;
    std::ofstream checks,rows;
    Audit(const std::filesystem::path& path,std::vector<std::string> expected):output(path),ids(std::move(expected)) {
        need(!std::filesystem::exists(output)&&std::filesystem::create_directories(output),"新規出力directoryが必要");
        checks.open(output/"checks.jsonl");rows.open(output/"audit.jsonl");need(bool(checks)&&bool(rows),"証拠を開けない");
    }
    void pass(const std::string& id) {
        need(std::find(ids.begin(),ids.end(),id)!=ids.end()&&passed.insert(id).second,"未宣言/重複ID: "+id);
        checks<<"{\"id\":"<<quoted(id)<<",\"pass\":true}\n";checks.flush();need(bool(checks),"checks書込失敗");
    }
    void observe(const char* stage,const Pipeline& pipeline) {
        const auto d=pipeline.diagnostics();
        rows<<std::setprecision(17)<<"{\"stage\":"<<quoted(stage)<<",\"generation\":"<<d.inputGeneration<<",\"session\":"<<d.session
            <<",\"checkpoint_start\":"<<d.checkpointStartFrame<<",\"checkpoint_used\":"<<d.checkpointUsed
            <<",\"initial_A_hit\":"<<d.loopReuse.initialCheckpointHit<<",\"initial_prefix_hit\":"<<d.loopReuse.initialPrefixCheckpointHit
            <<",\"seek_checkpoint_states\":"<<d.checkpointResidentStates<<",\"checkpoint_states\":"<<d.loopReuse.checkpointStates
            <<",\"checkpoint_peak\":"<<d.loopReuse.checkpointPeak<<",\"checkpoint_builds\":"<<d.checkpointBuilds
            <<",\"output_start\":"<<d.outputStartFrame<<",\"output_end\":"<<pipeline.loopOutputEndFrame()<<",\"seed_output\":"<<d.loopReuse.seedOutput
            <<",\"cold_discarded\":"<<d.loopReuse.coldDiscardedFrames<<",\"normal_discarded\":"<<d.discardedFrames
            <<",\"generated\":"<<d.generated<<",\"published\":"<<d.published<<",\"consumed\":"<<d.consumed
            <<",\"failed\":"<<d.failed<<",\"cancelled\":"<<d.cancelled<<",\"error\":"<<quoted(d.error)<<"}\n";
        rows.flush();need(bool(rows),"audit書込失敗");
    }
    void summary(bool ok,const std::string& error="") {
        const auto owners=Pipeline::executionOwnerCounts();
        std::ofstream stream(output/"SUMMARY.json");
        stream<<"{\"suite\":\"phase62_prefix_checkpoint\",\"status\":"<<quoted(ok?"PASS":"FAIL")<<",\"expected\":"<<ids.size()
            <<",\"executed\":"<<passed.size()<<",\"passed\":"<<passed.size()<<",\"run_complete\":"<<(ok?"true":"false")
            <<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"independent_fixed_raw_supplied\":true"
            <<",\"audio_device\":false,\"callback\":false,\"workgroup_promoted\":false,\"native_deadlines\":\"NOT_ASSESSED\",\"reason\":"<<quoted(error)<<"}\n";
        stream.flush();need(bool(stream),"SUMMARY書込失敗");
    }
};
struct FixedReference {
    std::filesystem::path path;
    std::size_t channels=0,frames=0,oa=0,shortEnd=0,longEnd=0,earlyA=0,earlyB=0,zeroEnd=0;
    void range(const SavedRange& actual,std::size_t a,std::size_t b)const {
        need(actual.oa==a&&actual.ob==b&&b>a&&actual.firstPeriod.size()==(b-a)*channels,"独立OA/OB・全ch長と不一致");
        std::ifstream stream(path,std::ios::binary);need(bool(stream),"凍結RAWを開けない");
        stream.seekg(std::streamoff(a*channels*sizeof(float)));
        for(std::size_t i=0;i<actual.firstPeriod.size();++i) {
            float value;need(bool(stream.read(reinterpret_cast<char*>(&value),sizeof(value))),"凍結RAWの区間が不足");
            need(std::isfinite(value)&&std::isfinite(actual.firstPeriod[i])&&
                std::bit_cast<std::uint32_t>(value)==std::bit_cast<std::uint32_t>(actual.firstPeriod[i]),"3周期RAWが独立固定Exactの全bitと違う");
        }
    }
    // Clearの通常ExactをBからEOFまで全量照合する。B保存点や未公開PCMを期待値に使わない。
    void suffix(Pipeline& pipeline,std::size_t from)const {
        need(pipeline.outputStartFrame()==from&&pipeline.diagnostics().outputFrames==frames,"Clearの独立B/全長が不一致");
        std::ifstream stream(path,std::ios::binary);need(bool(stream),"凍結RAWを開けない");
        stream.seekg(std::streamoff(from*channels*sizeof(float)));
        std::array<std::array<float,4096>,2> pcm{};float* pointers[]{pcm[0].data(),pcm[1].data()};
        std::size_t cursor=from;
        const auto end=Clock::now()+std::chrono::seconds(120);
        while(!pipeline.drained()) {
            need(!pipeline.failed(),pipeline.diagnostics().error);need(Clock::now()<end,"Clear全suffix期限");
            const auto n=std::min<std::size_t>(4096,pipeline.available());
            if(!n){std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
            const auto pulled=pipeline.pullAudio(pointers,n);
            need(pulled.wanted==n&&pulled.received==n&&pulled.outputBefore==cursor&&cursor+n<=frames,"Clear RAWの座標/欠落/重複/長さが不正");
            for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<channels;++ch) {
                float expected;need(bool(stream.read(reinterpret_cast<char*>(&expected),sizeof(expected))),"Clear参照不足");
                need(std::isfinite(expected)&&std::isfinite(pcm[ch][i])&&std::bit_cast<std::uint32_t>(expected)==std::bit_cast<std::uint32_t>(pcm[ch][i]),
                    "Clear全suffixの独立固定Exact bit不一致");
            }
            cursor+=n;bounded(pipeline);
        }
        need(cursor==frames&&stream.peek()==EOF,"Clear suffixのEOF/長さが不一致");
    }
};
struct Inputs {
    std::size_t warmEarly=0,warm=0,a=0,shortB=0,longB=0,earlyA=0,earlyB=0,zeroB=0;
};

Owner warmed(const char* input,p58::Configuration config,const Inputs& positions,bool two,std::uint32_t speed,Audit& audit,const char* label) {
    auto current=source(input,config);
    if(two) {
        replace(current,current->createSeek(positions.warmEarly,speed));
        need(current->diagnostics().checkpointResidentStates==1,"最初の通常seek保存点を作れない");
    }
    replace(current,current->createSeek(positions.warm,speed));
    const auto d=current->diagnostics();
    need(d.checkpointResidentStates==(config.seekCheckpoints?(two?2u:1u):0u),"既存通常seek保存点のfixture件数不正");
    need(!config.seekCheckpoints||d.checkpointBuilds>0,"通常seekから完全保存点が生成されない");
    need(d.reusedInput&&d.reusedAnalysis&&!d.renderingRequested,"通常seekでlease/解析を共有しない/誤ってPlayした");
    audit.observe(label,*current);bounded(*current);return current;
}
void prefixResult(Pipeline& pipeline,bool expectedHit,std::size_t independentA,std::size_t independentB) {
    const auto d=pipeline.diagnostics();
    need(pipeline.loopOutputStartFrame()==independentA&&pipeline.loopOutputEndFrame()==independentB,"独立MapのOA/OBと不一致");
    need(!d.loopReuse.initialCheckpointHit&&d.loopReuse.initialPrefixCheckpointHit==expectedHit,"通常seek prefixと固定A hitを混同/期待と不一致");
    need(d.checkpointStartFrame<=independentA&&d.checkpointStartFrame+d.loopReuse.coldDiscardedFrames==independentA,"PからAへのExact破棄計数不一致");
    need(expectedHit?d.checkpointStartFrame>0:d.checkpointStartFrame==0,"既存P省略/cold fallbackが不正");
    need(d.consumed==independentA&&pipeline.loopReadCycle()==0&&!d.renderingRequested,"初期準備で消費/周回/Playが進んだ");bounded(pipeline);
}
void positive(const char* input,p58::Configuration config,const Inputs& p,const FixedReference& ref,bool two,bool longRange,Audit& audit) {
    auto current=warmed(input,config,p,two,1000000,audit,two?"two_seek_points":"one_seek_point");
    const auto generation=current->inputGeneration();
    const auto newestSeekStart=current->outputStartFrame();
    replace(current,loop(*current,p.a,longRange?p.longB:p.shortB,1000000));
    prefixResult(*current,true,ref.oa,longRange?ref.longEnd:ref.shortEnd);
    need(current->diagnostics().checkpointStartFrame>=newestSeekStart,"P<=Aのうち新しい通常保存点を選択しなかった");
    audit.observe(longRange?"prefix_uncached_ready":"prefix_short_ready",*current);audit.pass(longRange?"P02.two_points_latest_compatible_hit":"P01.existing_seek_point_hit");
    const auto range=collect(*current,p.a,longRange?p.longB:p.shortB);
    ref.range(range,ref.oa,longRange?ref.longEnd:ref.shortEnd);
    const auto seed=current->diagnostics().loopReuse.seedOutput;
    need(current->diagnostics().loopReuse.cacheBytes==(longRange?0u:range.firstPeriod.size()*sizeof(float)),"短cache/長非cache条件を通らない");
    audit.pass(longRange?"R02.uncached_three_cycles_fixed_raw":"R01.cached_three_cycles_fixed_raw");
    // 同速度のClearは、固定A seedだけをexecution ownerへcloneする。
    // [A,B)の3周+17を既に読んでおり、未公開B近傍PCMの再利用では通せない。
    const auto target=longRange?p.longB:p.shortB,independentB=longRange?ref.longEnd:ref.shortEnd;
    replace(current,current->createSeek(target,1000000));
    const auto d=current->diagnostics();
    need(current->inputGeneration()==generation&&d.checkpointStartFrame==seed&&seed<=ref.oa&&seed<independentB&&
        d.discardedFrames==independentB-seed,"Clearが固定A prefix以外を復元/破棄座標不一致");
    audit.observe(longRange?"clear_from_uncached_A_seed":"clear_from_cached_A_seed",*current);
    audit.pass(longRange?"C02.uncached_clear_uses_A_seed":"C01.cached_clear_uses_A_seed");
    ref.suffix(*current,independentB);audit.pass(longRange?"C04.uncached_clear_full_suffix_raw":"C03.cached_clear_full_suffix_raw");
    retire(current);
}
enum class Fallback {AfterA,Speed,NonDynamic,Disabled,Zero};
void fallback(const char* input,p58::Configuration config,const Inputs& p,const FixedReference& ref,Fallback mode,Audit& audit) {
    if(mode==Fallback::NonDynamic){config.dynamicTransitions=false;config.scheduling=p58::WorkerScheduling::Standard;}
    if(mode==Fallback::Disabled)config.seekCheckpoints=false;
    auto current=warmed(input,config,p,false,mode==Fallback::Speed?1250000:1000000,audit,"fallback_normal_seek");
    const bool early=mode==Fallback::AfterA,zero=mode==Fallback::Zero;
    const auto a=zero?0:early?p.earlyA:p.a,b=zero?p.zeroB:early?p.earlyB:p.shortB;
    const auto oa=zero?0:early?ref.earlyA:ref.oa,ob=zero?ref.zeroEnd:early?ref.earlyB:ref.shortEnd;
    if(early||zero)need(current->outputStartFrame()>oa,"P>A fixtureになっていない");
    replace(current,loop(*current,a,b,1000000));prefixResult(*current,false,oa,ob);audit.observe("cold_fallback",*current);
    const auto range=collect(*current,a,b);ref.range(range,oa,ob);
    const char* id=mode==Fallback::AfterA?"F01.point_after_A_cold_raw":mode==Fallback::Speed?"F02.speed_mismatch_cold_raw":
        mode==Fallback::NonDynamic?"F03.non_dynamic_cold_raw":mode==Fallback::Disabled?"F04.seek_checkpoint_opt_out_cold_raw":"F05.A0_cold_raw";
    audit.pass(id);retire(current);
}
void cancellation(const char* input,p58::Configuration config,const Inputs& p,const FixedReference& ref,Audit& audit) {
    auto current=warmed(input,config,p,true,1000000,audit,"cancel_two_valid_points");
    auto cancelled=loop(*current,p.a,p.shortB,1000000);
    // Nativeの外側seekVersionが旧準備を取消す契約を、stop/joinで再現する。
    // 失効版に新しい有効版の2保存点を奪わせ、cold成功させる要求は加えない。
    cancelled->stop();const auto before=cancelled->diagnostics();bool refused=false;
    try{cancelled->start();}catch(const std::logic_error&){refused=true;}
    const auto after=cancelled->diagnostics();
    need(refused&&before.finalDataAvailable&&before.cancelled&&after.cancelled&&after.finalDataAvailable&&
        !before.generated&&!before.published&&!before.consumed&&!after.generated&&!after.published&&!after.consumed&&
        !after.loopReuse.initialCheckpointHit&&!after.loopReuse.initialPrefixCheckpointHit&&cancelled->available()==0&&
        after.loopReuse.checkpointStates==2&&current->diagnostics().checkpointResidentStates==2,"取消版が復活/PCM公開/有効保存点を奪った");
    audit.observe("cancelled_never_started",*cancelled);audit.pass("V01.cancelled_preparation_never_resurrects");cancelled.reset();
    replace(current,loop(*current,p.a,p.shortB,1000000));prefixResult(*current,true,ref.oa,ref.shortEnd);
    const auto range=collect(*current,p.a,p.shortB);ref.range(range,ref.oa,ref.shortEnd);audit.observe("new_version_prefix_hit",*current);
    audit.pass("V02.new_preparation_keeps_valid_points_raw");retire(current);
}
}

int main(int argc,char** argv) {
    std::unique_ptr<Audit> audit;
    try {
        need(argc==12,"INPUT preset REF.f32 FROZEN_BINARY OA OBshort OBlong OAearly OBearly OB0 NEW_OUTPUT");
        const std::string preset=argv[2];need(preset=="baseline"||preset=="candidate","preset不正");
        ts::WavStreamReader wav(argv[1]);const auto rate=std::size_t(wav.sampleRate());
        Inputs p{rate/4+7,rate*6+17,rate*8+31,0,0,rate/2+11,0,rate/10};
        p.shortB=p.a+rate/10;p.longB=p.a+rate*3+1;p.earlyB=p.earlyA+rate/10;
        need(wav.channels()>=1&&wav.channels()<=2&&rate>=32000&&p.longB+rate/2<wav.frames(),"32kHz以上・12秒以上の小さな入力が必要");
        FixedReference ref{argv[3],wav.channels(),wav.frames(),std::stoull(argv[5]),std::stoull(argv[6]),std::stoull(argv[7]),
            std::stoull(argv[8]),std::stoull(argv[9]),std::stoull(argv[10])};
        need(std::filesystem::file_size(ref.path)==ref.frames*ref.channels*sizeof(float),"独立固定1倍RAWの全曲/全ch長不一致");
        need(ref.oa<ref.shortEnd&&ref.shortEnd<ref.longEnd&&ref.longEnd<ref.frames&&ref.earlyA<ref.earlyB&&ref.earlyB<ref.oa&&
            ref.zeroEnd>0&&ref.zeroEnd<ref.earlyA&&ref.shortEnd-ref.oa<=96000&&ref.longEnd-ref.oa>96000,"独立Map座標/短長cache条件不正");
        const std::vector<std::string> ids{"P01.existing_seek_point_hit","P02.two_points_latest_compatible_hit",
            "R01.cached_three_cycles_fixed_raw","R02.uncached_three_cycles_fixed_raw",
            "C01.cached_clear_uses_A_seed","C02.uncached_clear_uses_A_seed","C03.cached_clear_full_suffix_raw","C04.uncached_clear_full_suffix_raw",
            "F01.point_after_A_cold_raw","F02.speed_mismatch_cold_raw","F03.non_dynamic_cold_raw","F04.seek_checkpoint_opt_out_cold_raw","F05.A0_cold_raw",
            "V01.cancelled_preparation_never_resurrects","V02.new_preparation_keeps_valid_points_raw","Z01.all_resources_and_inputs_unchanged"};
        audit=std::make_unique<Audit>(argv[11],ids);
        const auto inputSha=fileSha(argv[1]),binarySha=fileSha(std::filesystem::absolute(argv[0])),rawSha=fileSha(ref.path),referenceSha=fileSha(argv[4]);
        {
            std::ofstream expected(audit->output/"EXPECTED.json");
            expected<<"{\"suite\":\"phase62_prefix_checkpoint\",\"expected\":"<<ids.size()<<",\"required_ids\":[";
            for(std::size_t i=0;i<ids.size();++i)expected<<(i?",":"")<<quoted(ids[i]);
            expected<<"],\"input_sha256\":"<<quoted(inputSha)<<",\"binary_sha256\":"<<quoted(binarySha)<<",\"reference_raw_sha256\":"<<quoted(rawSha)
                <<",\"reference_binary_sha256\":"<<quoted(referenceSha)<<",\"required_reference_binary_sha256\":"<<quoted(frozenSha)<<",\"preset\":"<<quoted(preset)
                <<",\"speed_micros\":1000000,\"input_frames\":"<<wav.frames()<<",\"channels\":"<<wav.channels()<<",\"A\":"<<p.a<<",\"Bshort\":"<<p.shortB
                <<",\"Blong\":"<<p.longB<<",\"early_A\":"<<p.earlyA<<",\"early_B\":"<<p.earlyB<<",\"B0\":"<<p.zeroB
                <<",\"reference_positions\":["<<ref.oa<<','<<ref.shortEnd<<','<<ref.longEnd<<','<<ref.earlyA<<','<<ref.earlyB<<",0,"<<ref.zeroEnd<<']'
                <<",\"max_owners\":2,\"max_checkpoint_states\":2,\"loop_cycles\":3,\"extra_frames\":17,\"gain\":1,\"audio_device\":false,\"callback\":false"
                <<",\"cancel_contract\":\"outer cancellation stops/joins old epoch; valid new-version checkpoints are retained; stale epoch cold success is not required\"}\n";
            expected.flush();need(bool(expected),"EXPECTED書込失敗");
        }
        need(referenceSha==frozenSha,"凍結参照binaryの現SHAが契約と違う");
        p58::Configuration config;config.speedMicros=1000000;config.candidate=preset=="candidate";config.verifyPcm=false;config.residentInput=true;
        config.seekCheckpoints=true;config.dynamicTransitions=true;config.scheduling=p58::WorkerScheduling::AudioWorkgroup;config.boundedEpochReservations=true;
        positive(argv[1],config,p,ref,false,false,*audit);positive(argv[1],config,p,ref,true,true,*audit);
        for(auto mode:{Fallback::AfterA,Fallback::Speed,Fallback::NonDynamic,Fallback::Disabled,Fallback::Zero})fallback(argv[1],config,p,ref,mode,*audit);
        cancellation(argv[1],config,p,ref,*audit);
        const auto owners=Pipeline::executionOwnerCounts();need(!owners.alive&&owners.peak<=2,"全owner退役/上限不正");
        need(fileSha(argv[1])==inputSha&&fileSha(std::filesystem::absolute(argv[0]))==binarySha&&fileSha(ref.path)==rawSha&&fileSha(argv[4])==referenceSha,"入力/host/凍結RAW/凍結binaryが変更された");
        audit->pass("Z01.all_resources_and_inputs_unchanged");need(audit->passed.size()==audit->ids.size(),"宣言IDが未完了");audit->summary(true);
        std::cout<<"PHASE62_PREFIX_CHECKPOINT_COMPLETE expected="<<ids.size()<<" executed="<<audit->passed.size()<<" passed="<<audit->passed.size()<<'\n';return 0;
    }catch(const std::exception& error){std::cerr<<"FAIL "<<error.what()<<'\n';if(audit)try{audit->summary(false,error.what());}catch(...){}return 1;}
}
