// mono PV専用の下位診断。build/run/audioは親が直列で実行する。
// CLI: 引数なし。54固定計時標本。native whole-CPU/PCM oracle/RT承認ではない。
// 参照は独立Frozen5674PV + Frozen5674PhaseLocker。privateは変更も直読もしない。
/* 例: c++ -O3 -DNDEBUG -std=c++20 -arch arm64 -Isrc -Itests THIS.cpp
 tests/reference/performance_response/Frozen5674PhaseVocoder.cpp
 tests/reference/performance_response/Frozen5674PhaseLocker.cpp
 src/prototype/Phase35PhaseVocoder.cpp src/dsp/PhaseLocker.cpp -o NEW_BUILD/mono_vocoder_bench */
#include "prototype/Phase35PhaseVocoder.h"
#include "reference/performance_response/Frozen5674PhaseVocoder.h"
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <exception>
#include <iomanip>
#include <iostream>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

namespace {
using Current=ts::prototype::Phase35PhaseVocoder;
using Frozen=ts::prototype::Frozen5674PhaseVocoder;
using Complex=std::complex<float>;
using Clock=std::chrono::steady_clock;
constexpr std::array<std::size_t,3> fftSizes{1024,4096,8192};
constexpr std::array<double,3> hsRatios{.5,1.,2.};
constexpr std::array<const char*,3> ratioNames{"050","100","200"};
constexpr unsigned frames=512,repeats=3,forkAt=255,forkFrames=16;
constexpr std::size_t expectedCases=9,expectedSamples=54;
constexpr std::uint64_t expectedMainPairs=expectedCases*frames;
constexpr std::uint64_t expectedForkPairs=expectedCases*forkFrames;
constexpr std::uint64_t expectedCopyCrossPairs=2*expectedForkPairs;
constexpr std::uint64_t expectedComplexPre=3*(513+2049+4097)*(frames+3*forkFrames);
constexpr std::uint64_t expectedComplexTimedFinal=3*(513+2049+4097)*repeats*2;
static_assert(sizeof(Complex)==sizeof(std::uint64_t));

struct Failure:std::runtime_error {
    std::string kind;
    Failure(std::string k,std::string why):std::runtime_error(std::move(why)),kind(std::move(k)){}
};
void need(bool yes,std::string_view why){if(!yes)throw Failure("COVERAGE_OR_CONTRACT",std::string(why));}
std::string quote(std::string_view text){std::string s="\"";for(unsigned char c:text){if(c=='"'||c=='\\'){s+='\\';s+=char(c);}else if(c=='\n')s+="\\n";else if(c=='\r')s+="\\r";else if(c=='\t')s+="\\t";else if(c>=32)s+=char(c);}return s+'"';}
struct Counts {
    std::uint64_t mainPairs=0,forkPairs=0,copyCrossPairs=0,copyForks=0;
    std::uint64_t complexValues=0,floatValues=0,ownerEntries=0,peaks=0,publicStateComparisons=0;
};
void equalFloat(float a,float b,Counts& n,std::string_view why){
    if(!std::isfinite(a)||!std::isfinite(b))throw Failure("NONFINITE",std::string(why));
    ++n.floatValues;
    if(std::bit_cast<std::uint32_t>(a)!=std::bit_cast<std::uint32_t>(b))throw Failure("BIT_MISMATCH",std::string(why));
}
void equalComplex(const std::vector<Complex>& a,const std::vector<Complex>& b,Counts& n){
    need(a.size()==b.size(),"complex length");
    for(std::size_t k=0;k<a.size();++k){
        if(!std::isfinite(a[k].real())||!std::isfinite(a[k].imag())||!std::isfinite(b[k].real())||!std::isfinite(b[k].imag()))
            throw Failure("NONFINITE","complex bin "+std::to_string(k));
        ++n.complexValues;
        if(std::bit_cast<std::uint64_t>(a[k])!=std::bit_cast<std::uint64_t>(b[k]))
            throw Failure("BIT_MISMATCH","complex bin "+std::to_string(k));
    }
}
// 公開getterが示す情報をコピーする。隠れたphase/initialized等の全状態直読ではない。
struct PublicPeak {int bin;float position,magnitude;};
struct PublicState {
    std::vector<int> owners;
    std::vector<float> magnitudes;
    std::vector<PublicPeak> peaks;
};
template<class P> PublicState publicState(const P& pv){
    const auto& locker=pv.phaseLocker();PublicState s;
    s.owners=locker.ownerPeak();s.magnitudes=locker.magnitudes();s.peaks.reserve(locker.peaks().size());
    for(const auto& p:locker.peaks())s.peaks.push_back({p.bin,p.position,p.magnitude});return s;
}
void equalPublic(const PublicState& a,const PublicState& b,Counts& n){
    need(a.owners.size()==b.owners.size()&&a.magnitudes.size()==b.magnitudes.size()&&a.peaks.size()==b.peaks.size(),"public state lengths");
    for(std::size_t k=0;k<a.owners.size();++k){++n.ownerEntries;if(a.owners[k]!=b.owners[k])throw Failure("BIT_MISMATCH","public peak owner");}
    for(std::size_t k=0;k<a.magnitudes.size();++k)equalFloat(a.magnitudes[k],b.magnitudes[k],n,"public magnitude");
    for(std::size_t k=0;k<a.peaks.size();++k){++n.peaks;if(a.peaks[k].bin!=b.peaks[k].bin)throw Failure("BIT_MISMATCH","public peak bin");equalFloat(a.peaks[k].position,b.peaks[k].position,n,"public peak position");equalFloat(a.peaks[k].magnitude,b.peaks[k].magnitude,n,"public peak magnitude");}
    ++n.publicStateComparisons;
}
void noPublishedPolar(const Current& pv,const std::vector<Complex>& input){
    const auto view=pv.inputPolarView();need(!view.validFor(pv,input.data(),input.size()),"mono/null-owner unexpectedly published input polar view");
}
struct FrameSpec {double hs;bool reset,selective;float strength;int analysisHop;};
struct Case {
    std::size_t fft;unsigned ratio;
    std::string id;
    std::vector<Complex> input,expectedOutput;
    std::array<FrameSpec,frames> specs;
    PublicState expectedPublic;
    bool validated=false;
};
Case makeCase(std::size_t fft,unsigned ratio){
    Case c;c.fft=fft;c.ratio=ratio;c.id="mono_fft"+std::to_string(fft)+"_hs"+ratioNames[ratio];
    const auto bins=fft/2+1;c.input.resize(bins);
    // 既存PerformanceDspBenchのchannel=0と同じ正のmagnitude/有限phase。
    for(std::size_t k=0;k<bins;++k){
        const float magnitude=float(.1+((k*19)%997)/13.);
        const float phase=float((k*17)%1000)*.006f;
        if(!std::isfinite(magnitude)||!std::isfinite(phase))throw Failure("NONFINITE","input magnitude/phase");
        need(magnitude>0,"positive fixture magnitude");
        c.input[k]=std::polar(magnitude,phase);
        if(!std::isfinite(c.input[k].real())||!std::isfinite(c.input[k].imag()))throw Failure("NONFINITE","input spectrum");
    }
    const auto ha=int(fft/4);
    for(unsigned f=0;f<frames;++f){c.specs[f]={f?double(ha)*hsRatios[ratio]:0.0,f%64==0,false,1.0f,ha};
        if(!std::isfinite(c.specs[f].hs))throw Failure("NONFINITE","synthesis hop");need(c.specs[f].hs>=0,"nonnegative synthesis hop");}
    return c;
}
template<class P> void frame(P& pv,const Case& c,unsigned i,std::vector<Complex>& output){
    const auto& s=c.specs[i];
    pv.process(c.input.data(),output.data(),s.hs,s.reset,s.selective,s.strength,nullptr,s.analysisHop);
}
std::uint64_t fingerprint(const std::vector<Complex>& spectrum){
    std::uint64_t h=14695981039346656037ULL;
    for(const auto& value:spectrum){
        if(!std::isfinite(value.real())||!std::isfinite(value.imag()))throw Failure("NONFINITE","fingerprint spectrum");
        h^=std::bit_cast<std::uint64_t>(value);h*=1099511628211ULL;
    }return h;
}
void validateCase(Case& c,Counts& n){
    Current current(c.fft,int(c.fft/4),true,48000);Frozen old(c.fft,int(c.fft/4),true,48000);
    std::vector<Complex> a(c.input.size()),b(a.size()),fa(a.size()),fb(a.size());
    std::optional<Current> currentFork;std::optional<Frozen> oldFork;
    for(unsigned f=0;f<frames;++f){
        frame(current,c,f,a);frame(old,c,f,b);
        equalComplex(a,b,n);equalPublic(publicState(current),publicState(old),n);noPublishedPolar(current,c.input);++n.mainPairs;
        if(f==forkAt){currentFork.emplace(current);oldFork.emplace(old);++n.copyForks;}
        if(f>forkAt&&f<=forkAt+forkFrames){
            frame(*currentFork,c,f,fa);frame(*oldFork,c,f,fb);
            equalComplex(fa,fb,n);equalPublic(publicState(*currentFork),publicState(*oldFork),n);noPublishedPolar(*currentFork,c.input);++n.forkPairs;
            equalComplex(fa,a,n);equalPublic(publicState(*currentFork),publicState(current),n);++n.copyCrossPairs;
            equalComplex(fb,b,n);equalPublic(publicState(*oldFork),publicState(old),n);++n.copyCrossPairs;
        }
    }
    c.expectedOutput=b;c.expectedPublic=publicState(old);c.validated=true;
}
struct Sample {
    std::string id,version,caseId,kind,detail;
    std::size_t fft=0;unsigned ratio=0,repeat=0;
    std::optional<double> cpu,wall;
    std::optional<std::uint64_t> spectrum;
    bool pass=false;
};
double threadCpu(){timespec t{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)!=0)throw Failure("TIMING","thread CPU clock failed");return double(t.tv_sec)+double(t.tv_nsec)*1e-9;}
std::string sampleId(const Case& c,unsigned repeat,bool frozen){return c.id+"_r0"+std::to_string(repeat)+(frozen?"_frozen5674":"_current05pv");}
template<bool frozen> Sample timed(const Case& c,unsigned repeat,Counts& finalChecks){
    using P=std::conditional_t<frozen,Frozen,Current>;
    Sample s;s.id=sampleId(c,repeat,frozen);s.version=frozen?"frozen5674":"current05pv";s.caseId=c.id;s.fft=c.fft;s.ratio=c.ratio;s.repeat=repeat;
    try{
        need(c.validated,"prevalidation required");
        // 確保/入力生成/全有限性検査/比較/標準出力はこのCPU窓に入れない。
        P pv(c.fft,int(c.fft/4),true,48000);std::vector<Complex> output(c.input.size());
        const auto wall0=Clock::now();const auto cpu0=threadCpu();
        for(unsigned f=0;f<frames;++f)frame(pv,c,f,output);
        const auto cpu1=threadCpu();const auto wall1=Clock::now();
        s.cpu=cpu1-cpu0;s.wall=std::chrono::duration<double>(wall1-wall0).count();
        if(!std::isfinite(*s.cpu)||!std::isfinite(*s.wall)||*s.cpu<=0||*s.wall<=0)throw Failure("TIMING","nonfinite/nonpositive timing");
        // 事前全frame比較に加え、実計時後の最終complex/公開状態も独立期待値へ照合。
        equalComplex(output,c.expectedOutput,finalChecks);equalPublic(publicState(pv),c.expectedPublic,finalChecks);
        if constexpr(!frozen)noPublishedPolar(pv,c.input);
        s.spectrum=fingerprint(output);s.pass=true;
    }catch(const Failure& e){s.kind=e.kind;s.detail=e.what();}
     catch(const std::exception& e){s.kind="EXCEPTION";s.detail=e.what();}
    return s;
}
void number(std::ostream& out,const std::optional<double>& x){if(x&&std::isfinite(*x))out<<*x;else out<<"null";}
void writeSample(const Sample& s){
    std::cout<<"ROW {\"id\":"<<quote(s.id)<<",\"case\":"<<quote(s.caseId)<<",\"version\":"<<quote(s.version)<<",\"repeat\":"<<s.repeat<<",\"fft\":"<<s.fft<<",\"hs_ratio\":"<<hsRatios[s.ratio]<<",\"frames\":"<<frames<<",\"pass\":"<<(s.pass?"true":"false")<<",\"cpu_s\":";number(std::cout,s.cpu);std::cout<<",\"wall_s\":";number(std::cout,s.wall);std::cout<<",\"spectrum_fnv\":";if(s.spectrum)std::cout<<*s.spectrum;else std::cout<<"null";std::cout<<",\"failure_kind\":"<<quote(s.kind)<<",\"detail\":"<<quote(s.detail)<<"}\n";
}
void writeValues(const std::vector<double>& values){
    std::cout<<"{\"n\":"<<values.size()<<",\"values\":[";for(std::size_t i=0;i<values.size();++i)std::cout<<(i?",":"")<<values[i];std::cout<<']';
    if(!values.empty()){auto sorted=values;std::sort(sorted.begin(),sorted.end());double sum=0;for(auto x:values)sum+=x;const auto mid=sorted.size()/2;const auto median=sorted.size()%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2;std::cout<<",\"mean\":"<<sum/values.size()<<",\"median\":"<<median<<",\"min\":"<<sorted.front()<<",\"max\":"<<sorted.back();}std::cout<<'}';
}
void writeStats(const std::vector<Case>& cases,const std::vector<Sample>& samples){
    std::cout<<'[';bool first=true;
    for(const auto& c:cases){if(!first)std::cout<<',';first=false;std::cout<<"{\"case\":"<<quote(c.id)<<",\"cpu_s\":{";
        for(bool old:{true,false}){if(!old)std::cout<<',';const std::string version=old?"frozen5674":"current05pv";std::vector<double> values;for(const auto& s:samples)if(s.caseId==c.id&&s.version==version&&s.pass&&s.cpu)values.push_back(*s.cpu);std::cout<<quote(version)<<':';writeValues(values);}std::cout<<"},\"paired_current_minus_frozen_s\":[";
        for(unsigned repeat=1;repeat<=repeats;++repeat){if(repeat>1)std::cout<<',';const Sample *a=nullptr,*b=nullptr;for(const auto& s:samples)if(s.caseId==c.id&&s.repeat==repeat){if(s.version=="frozen5674")a=&s;else b=&s;}std::cout<<"{\"repeat\":"<<repeat<<",\"delta\":";if(a&&b&&a->pass&&b->pass&&a->cpu&&b->cpu)std::cout<<*b->cpu-*a->cpu;else std::cout<<"null";std::cout<<'}';}std::cout<<"]}";
    }std::cout<<']';
}
std::vector<std::string> expectedIds(){
    std::vector<std::string> ids;
    for(unsigned repeat=1;repeat<=repeats;++repeat)for(auto fft:fftSizes)for(unsigned r=0;r<hsRatios.size();++r){Case c;c.fft=fft;c.ratio=r;c.id="mono_fft"+std::to_string(fft)+"_hs"+ratioNames[r];for(unsigned turn=0;turn<2;++turn)ids.push_back(sampleId(c,repeat,repeat%2?turn==0:turn!=0));}
    return ids;
}
void expected(const std::vector<std::string>& ids){
    std::cout<<"EXPECTED {\"schema\":\"mono-vocoder-bench-v1\",\"classification\":\"SCALAR_DIAGNOSTIC\",\"expected_samples\":54,\"expected_prevalidation_cases\":9,\"frames_per_sample\":512,\"repeats\":3,\"FFT\":[1024,4096,8192],\"hs_ratios\":[0.5,1,2],\"sample_rate\":48000,\"phase_locking\":true,\"shared_owners\":null,\"external_time_map\":null,\"tracker\":false,\"coherence\":false,\"input\":\"Constant spectrum: same channel0 positive-magnitude formula as PerformanceDspBench. No WAV/FFT/iFFT/FIR/playback.\",\"first_hs\":0,\"reset\":\"frame%64==0\",\"selective\":false,\"strength\":1,\"analysis_hop_override\":\"FFT/4\",\"warmup_frames\":0,\"order\":\"r1 frozen/current, r2 current/frozen, r3 frozen/current per case\",\"expected_main_frame_pairs\":"<<expectedMainPairs<<",\"expected_copy_frame_pairs\":"<<expectedForkPairs<<",\"expected_copy_vs_main_pairs\":"<<expectedCopyCrossPairs<<",\"copy_at_frame\":255,\"copy_future_frames\":16,\"private_state_direct_read\":false,\"state_scope\":\"Every frame output and public owner/magnitudes/peaks, then copied continuation output/public state. No proof of all private state bits.\",\"reference_commit\":\"5674bd982d98caacaa3e87cdeae5bfc0b01c66ef\",\"reference_identity_scope\":\"Compile wrapper must verify PROVENANCE.json and frozen/current source SHA; host does not rehash source files.\",\"reference_provenance_expected_sha256\":\"2e76c422a19685583dc266da5ae1478c2806742c722aac751336f6f4ed21fae7\",\"current_pv_cpp_expected_sha256\":\"49168f671ebdc8bd6fbe882872df706a5383328d55096b7a060e3b3ca11ae4ce\",\"required_ids\":[";
    for(std::size_t i=0;i<ids.size();++i)std::cout<<(i?",":"")<<quote(ids[i]);std::cout<<"]}\n"<<std::flush;
}
}
int main(int argc,char**){
    if(argc!=1){std::cerr<<"usage: mono_vocoder_bench (no arguments)\n";return 2;}
    std::cout<<std::setprecision(17);const auto ids=expectedIds();expected(ids);
    Counts pre,post;std::vector<Case> cases;std::vector<Sample> samples;std::size_t prePassed=0,preFailed=0;
    std::uint64_t nonfiniteFailures=0,bitFailures=0,otherFailures=0;
    const auto failed=[&](const std::string& kind){if(kind=="NONFINITE")++nonfiniteFailures;else if(kind=="BIT_MISMATCH")++bitFailures;else ++otherFailures;};
    try{
        need(ids.size()==expectedSamples&&std::set<std::string>(ids.begin(),ids.end()).size()==expectedSamples,"54 unique expected IDs");
        cases.reserve(expectedCases);samples.reserve(expectedSamples);
        for(auto fft:fftSizes)for(unsigned ratio=0;ratio<hsRatios.size();++ratio){
            cases.push_back(makeCase(fft,ratio));auto& c=cases.back();std::string kind,detail;
            try{validateCase(c,pre);++prePassed;}catch(const Failure& e){kind=e.kind;detail=e.what();failed(kind);++preFailed;}catch(const std::exception& e){kind="EXCEPTION";detail=e.what();failed(kind);++preFailed;}
            std::cout<<"CHECK {\"id\":"<<quote(c.id)<<",\"pass\":"<<(c.validated?"true":"false")<<",\"failure_kind\":"<<quote(kind)<<",\"detail\":"<<quote(detail)<<",\"input_fnv\":"<<fingerprint(c.input)<<"}\n";
        }
        const bool preCoverage=prePassed==expectedCases&&preFailed==0&&pre.mainPairs==expectedMainPairs&&pre.forkPairs==expectedForkPairs&&pre.copyCrossPairs==expectedCopyCrossPairs&&pre.copyForks==expectedCases&&pre.complexValues==expectedComplexPre&&pre.publicStateComparisons==expectedMainPairs+expectedForkPairs+expectedCopyCrossPairs;
        if(preCoverage){
            // 9条件を全照合し終わるまで、1標本も速度計測を開始しない。
            for(unsigned repeat=1;repeat<=repeats;++repeat)for(const auto& c:cases)for(unsigned turn=0;turn<2;++turn){const bool old=repeat%2?turn==0:turn!=0;auto s=old?timed<true>(c,repeat,post):timed<false>(c,repeat,post);if(!s.pass)failed(s.kind);samples.push_back(std::move(s));writeSample(samples.back());}
        }
        std::set<std::string> actual;bool ordered=true;std::size_t passed=0;
        for(std::size_t i=0;i<samples.size();++i){actual.insert(samples[i].id);ordered=ordered&&i<ids.size()&&samples[i].id==ids[i];passed+=samples[i].pass;}
        const bool complete=samples.size()==expectedSamples&&actual.size()==expectedSamples&&ordered;
        const bool coverage=preCoverage&&post.complexValues==expectedComplexTimedFinal&&post.publicStateComparisons==expectedSamples;
        const bool pass=complete&&coverage&&passed==expectedSamples&&!nonfiniteFailures&&!bitFailures&&!otherFailures;
        std::cout<<"SUMMARY {\"schema\":\"mono-vocoder-bench-v1\",\"status\":"<<quote(pass?"PASS":"FAIL")<<",\"run_complete\":"<<(complete?"true":"false")<<",\"coverage_pass\":"<<(coverage?"true":"false")<<",\"expected_samples\":54,\"executed_samples\":"<<samples.size()<<",\"passed_samples\":"<<passed<<",\"failed_samples\":"<<samples.size()-passed<<",\"not_run_samples\":"<<expectedSamples-samples.size()<<",\"prevalidation_cases_passed\":"<<prePassed<<",\"prevalidation_cases_failed\":"<<preFailed<<",\"main_frame_pairs\":"<<pre.mainPairs<<",\"copy_frame_pairs\":"<<pre.forkPairs<<",\"copy_vs_main_pairs\":"<<pre.copyCrossPairs<<",\"copy_forks\":"<<pre.copyForks<<",\"prevalidation_complex_values\":"<<pre.complexValues<<",\"expected_prevalidation_complex_values\":"<<expectedComplexPre<<",\"timed_final_complex_values\":"<<post.complexValues<<",\"expected_timed_final_complex_values\":"<<expectedComplexTimedFinal<<",\"prevalidation_public_state_comparisons\":"<<pre.publicStateComparisons<<",\"timed_final_public_state_comparisons\":"<<post.publicStateComparisons<<",\"float_values_compared\":"<<pre.floatValues+post.floatValues<<",\"owner_entries_compared\":"<<pre.ownerEntries+post.ownerEntries<<",\"peak_entries_compared\":"<<pre.peaks+post.peaks<<",\"nonfinite_failures\":"<<nonfiniteFailures<<",\"bit_mismatch_failures\":"<<bitFailures<<",\"other_failures\":"<<otherFailures<<",\"private_state_direct_read\":false,\"actual_ids\":[";for(std::size_t i=0;i<samples.size();++i)std::cout<<(i?",":"")<<quote(samples[i].id);std::cout<<"],\"statistics\":";writeStats(cases,samples);std::cout<<",\"performance_pass\":null,\"whole_process_CPU_approval\":false,\"PCM_oracle\":false,\"RT_approval\":null,\"quality_approval\":null,\"physical_audio\":null,\"statistical_causality\":\"NOT_ASSESSED; fixed synthetic n3 only\"}\n";return pass?0:1;
    }catch(const std::exception& e){
        const auto* specific=dynamic_cast<const Failure*>(&e);const std::string kind=specific?specific->kind:"EXCEPTION";failed(kind);
        std::cout<<"SUMMARY {\"schema\":\"mono-vocoder-bench-v1\",\"status\":\"INCOMPLETE\",\"run_complete\":false,\"expected_samples\":54,\"executed_samples\":"<<samples.size()<<",\"not_run_samples\":"<<expectedSamples-samples.size()<<",\"detail\":"<<quote(e.what())<<",\"failure_kind\":"<<quote(kind)<<",\"nonfinite_failures\":"<<nonfiniteFailures<<",\"bit_mismatch_failures\":"<<bitFailures<<",\"other_failures\":"<<otherFailures<<",\"performance_pass\":null,\"whole_process_CPU_approval\":false,\"PCM_oracle\":false,\"RT_approval\":null,\"quality_approval\":null}\n";return 1;
    }
}
