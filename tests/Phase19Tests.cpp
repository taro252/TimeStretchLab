#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include "dsp/Phase18PcmCache.h"
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {
void require(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
ts::StretchConfig frozen(const std::filesystem::path& path) {
    ts::WavStreamReader input(path);
    ts::StretchConfig config;
    config.sampleRate=input.sampleRate();config.channels=static_cast<int>(input.channels());
    config.timeRatio=2;config.enableMultiResolution=true;
    config.qualityMode=ts::QualityMode::Experimental;
    config.enablePhaseLocking=true;config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true;config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true;
    return config;
}
std::filesystem::path makeInput(const std::filesystem::path& directory,int seed) {
    constexpr std::size_t frames=48000*3;
    std::vector<float> left(frames),right(frames);
    for (std::size_t i=0;i<frames;++i) {
        left[i]=0.25f*std::sin(2*3.141592653589793*(437.3+seed)*i/48000.0);
        right[i]=0.8f*left[i];
    }
    left[12000+seed]=0.7f;right[12000+seed]=0.5f;
    const auto path=directory/("input_"+std::to_string(seed)+".wav");
    ts::WavStreamWriter writer(path,48000,2,frames);
    const float* planes[]={left.data(),right.data()};
    writer.write(planes,frames);writer.finish();
    return path;
}
void compareLease(const ts::VerifiedPcmCache& lease,ts::WavStreamReader& golden,
                  std::size_t frame,std::size_t count) {
    std::array<std::vector<float>,2> output={std::vector<float>(count),std::vector<float>(count)};
    float* planes[]={output[0].data(),output[1].data()};
    lease.readFrames(frame,count,planes);
    for (std::size_t i=0;i<count;++i) for (std::size_t c=0;c<2;++c)
        require(output[c][i]==golden.sample(c,frame+i),"Verified cache differs from Golden");
}
void generate(ts::Phase18PcmCache& cache) {
    cache.beginGeneration();cache.wait();
    if (!cache.generationError().empty()) throw std::runtime_error(cache.generationError());
}
void testLease(const std::filesystem::path& root,const std::filesystem::path& input) {
    const auto goldenPath=root/"golden.wav";
    ts::WavStreamReader source(input);
    ts::WavStreamWriter golden(goldenPath,48000,2,source.frames()*2);
    ts::Phase13StreamingEngine(frozen(input)).processFile(input,
        [&](const float* const* planes,std::size_t frames) {golden.write(planes,frames);});
    golden.finish();
    ts::WavStreamReader reference(goldenPath);
    ts::Phase18PcmCache cache(input,root/"lease",frozen(input));
    generate(cache);
    double firstSeconds=0,repeatedSeconds=0;
    auto lease=cache.acquireVerified(&firstSeconds);
    require(bool(lease),"Initial full verification failed");
    for (int i=0;i<1000;++i) {
        auto again=cache.acquireVerified(&repeatedSeconds);
        require(again.get()==lease.get(),"Seek did not reuse verified descriptor");
    }
    for (auto frame:{std::size_t(0),std::size_t(12345),reference.frames()/2,
                    reference.frames()-8192})
        compareLease(*lease,reference,frame,8192);
    const auto moved=root/"renamed_while_open.wav";
    std::filesystem::rename(cache.cachePath(),moved);
    compareLease(*lease,reference,reference.frames()/3,8192);
    std::filesystem::remove(moved);
    compareLease(*lease,reference,reference.frames()/3,8192);
    lease.reset();cache.invalidateSession();
    generate(cache);
    lease=cache.acquireVerified();
    require(bool(lease),"Regenerated cache invalid");
    {
        std::fstream damage(cache.cachePath(),std::ios::binary|std::ios::in|std::ios::out);
        damage.seekp(44+8192);damage.put('X');
    }
    bool detected=false;
    try {compareLease(*lease,reference,0,4096);}
    catch (const std::runtime_error&) {detected=true;}
    require(detected,"In-place cache corruption was played");
    lease.reset();cache.invalidateSession();
    require(!cache.acquireVerified(),"Corrupt cache was accepted on reload");
    generate(cache);
    lease=cache.acquireVerified();
    require(bool(lease),"Repair failed");
    {
        std::filesystem::resize_file(cache.cachePath(),44);
        bool failed=false;
        try {compareLease(*lease,reference,0,4096);}
        catch (const std::runtime_error&) {failed=true;}
        require(failed,"Truncated cache read was not rejected");
    }
    lease.reset();cache.invalidateSession();
    // A descriptor is associated with the prepared input; replacing that path
    // must force a reload rather than reusing its old TimeMap.
    const auto replacement=makeInput(root,99);
    std::filesystem::rename(replacement,input);
    bool rejected=false;
    try {(void)cache.acquireVerified();}
    catch (const std::runtime_error&) {rejected=true;}
    require(rejected,"Replaced input was accepted");
    std::cout << "lease: first_validation=" << firstSeconds
              << " repeated_seek_validation=" << repeatedSeconds
              << " rename/delete/corruption/read-failure/input-replacement passed\n";
}
void testQuota(const std::filesystem::path& root,
               const std::array<std::filesystem::path,3>& inputs) {
    const ts::Phase19CachePolicy defaults;
    require(defaults.maximumBytes==2ULL*1024*1024*1024 &&
        defaults.freeSpaceFraction==0.10,"Default cache quota changed");
    ts::Phase19CachePolicy lowSpace;
    lowSpace.freeSpaceFraction=1e-12;
    ts::Phase18PcmCache limited(inputs[0],root/"low_space",frozen(inputs[0]),lowSpace);
    limited.beginGeneration();limited.wait();
    require(limited.generationError().find("capacity")!=std::string::npos,
        "Free-space fraction did not stop generation");
    ts::Phase19CachePolicy one;
    one.maximumBytes=2'500'000;one.freeSpaceFraction=1;
    ts::Phase18PcmCache a(inputs[0],root/"quota",frozen(inputs[0]),one);
    ts::Phase18PcmCache b(inputs[1],root/"quota",frozen(inputs[1]),one);
    generate(a);
    auto active=a.acquireVerified();
    require(bool(active),"First cache missing");
    b.beginGeneration();b.wait();
    require(b.generationError().find("capacity")!=std::string::npos,
            "Quota did not protect active cache");
    active.reset();a.invalidateSession();
    generate(b);
    require(bool(b.acquireVerified()),"LRU replacement cache missing");
    require(!std::filesystem::exists(a.cachePath()),"Old cache was not evicted");

    ts::Phase19CachePolicy two;
    two.maximumBytes=5'000'000;two.freeSpaceFraction=1;
    const auto directory=root/"lru";
    ts::Phase18PcmCache first(inputs[0],directory,frozen(inputs[0]),two);
    ts::Phase18PcmCache second(inputs[1],directory,frozen(inputs[1]),two);
    ts::Phase18PcmCache third(inputs[2],directory,frozen(inputs[2]),two);
    generate(first);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    generate(second);
    auto recentlyUsed=first.acquireVerified();
    require(bool(recentlyUsed),"LRU touch failed");
    recentlyUsed.reset();first.invalidateSession();
    generate(third);
    require(std::filesystem::exists(first.cachePath()),"Recently used cache was evicted");
    require(!std::filesystem::exists(second.cachePath()),"Least recent cache survived");
    require(std::filesystem::exists(third.cachePath()),"New LRU cache missing");
    std::cout << "quota: active lease protected, capacity fallback and LRU passed\n";
}
void testFailures(const std::filesystem::path& root,
                  const std::filesystem::path& input) {
    const auto directory=root/"recovery";
    ts::Phase18PcmCache cache(input,directory,frozen(input));
    const auto orphan=directory/(cache.key()+".crashed.tmp.wav");
    {std::ofstream file(orphan);file << "incomplete";}
    const auto unpublished=cache.cachePath();
    {std::ofstream file(unpublished);file << "published before metadata";}
    ts::Phase18PcmCache next(input,directory,frozen(input));
    require(!std::filesystem::exists(orphan),"Crash orphan was not removed");
    require(!std::filesystem::exists(unpublished),"Unpublished cache was not removed");
    cache.beginGeneration();next.beginGeneration();
    cache.wait();next.wait();
    require(bool(cache.acquireVerified()) || bool(next.acquireVerified()),
            "Concurrent same-key generation failed");
    const auto noWrite=root/"write_failure";
    ts::Phase18PcmCache blocked(input,noWrite,frozen(input));
    (void)blocked.acquireVerified(); // create key lock before removing write permission
    std::filesystem::permissions(noWrite,
        std::filesystem::perms::owner_read|std::filesystem::perms::owner_exec,
        std::filesystem::perm_options::replace);
    blocked.beginGeneration();blocked.wait();
    std::filesystem::permissions(noWrite,std::filesystem::perms::owner_all,
        std::filesystem::perm_options::replace);
    require(!blocked.generationError().empty(),"Write failure was not reported");
    {
        std::fstream changed(input,std::ios::binary|std::ios::in|std::ios::out);
        changed.seekp(44+4096);changed.put('X');changed.flush();
    }
    bool rejected=false;
    try {(void)cache.acquireVerified();}
    catch (const std::runtime_error&) {rejected=true;}
    require(rejected,"Modified input was accepted after preparation");
    std::cout << "failures: concurrent key, orphan cleanup, write refusal and input mutation passed\n";
}
void testGolden(const std::filesystem::path& root,const std::filesystem::path& goldenRoot) {
    for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
        const auto input=goldenRoot/"input"/(std::string(name)+".wav");
        const auto reference=goldenRoot/"raw"/(std::string(name)+"_050.wav");
        ts::Phase18PcmCache cache(input,root/name,frozen(input));
        generate(cache);
        auto lease=cache.acquireVerified();
        require(bool(lease),"Golden cache lease missing");
        ts::WavStreamReader golden(reference);
        require(golden.frames()==lease->frames(),"Golden cache length differs");
        for (std::size_t at=0;at<golden.frames();at+=8192)
            compareLease(*lease,golden,at,std::min<std::size_t>(8192,golden.frames()-at));
        std::cout << name << ": verified descriptor and Golden raw samples exact\n";
    }
}
}

int main(int argc,char** argv) {
    const auto root=std::filesystem::temp_directory_path()/
        ("phase19_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    try {
        std::filesystem::create_directories(root);
        const std::array<std::filesystem::path,3> inputs={
            makeInput(root,1),makeInput(root,2),makeInput(root,3)};
        testLease(root,inputs[0]);
        testQuota(root,inputs);
        testFailures(root,inputs[1]);
        if (argc==2) testGolden(root,argv[1]);
        std::filesystem::remove_all(root);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Phase 19: " << error.what() << '\n';
        std::error_code ignored;
        std::filesystem::permissions(root/"write_failure",std::filesystem::perms::owner_all,
            std::filesystem::perm_options::replace,ignored);
        std::filesystem::remove_all(root,ignored);
        return 1;
    }
}
