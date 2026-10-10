#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include "dsp/Phase18PcmCache.h"
#include "dsp/Phase18SeekQueue.h"
#include <algorithm>
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
ts::StretchConfig frozen(ts::WavStreamReader& input) {
    ts::StretchConfig c;
    c.sampleRate=input.sampleRate();c.channels=static_cast<int>(input.channels());
    c.timeRatio=2.0;c.enableMultiResolution=true;c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
std::filesystem::path tempDirectory() {
    const auto path=std::filesystem::temp_directory_path()/
        ("phase18_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(path);
    return path;
}
void compareFiles(const std::filesystem::path& a,const std::filesystem::path& b) {
    if (std::filesystem::file_size(a)!=std::filesystem::file_size(b))
        throw std::runtime_error("Cache byte length differs from Golden");
    std::ifstream left(a,std::ios::binary),right(b,std::ios::binary);
    std::array<char,65536> x{},y{};
    while (left) {
        left.read(x.data(),x.size());right.read(y.data(),y.size());
        if (left.gcount()!=right.gcount() || !std::equal(x.begin(),x.begin()+left.gcount(),y.begin()))
            throw std::runtime_error("Cache bytes differ from Golden");
    }
}
void compareSeek(ts::Phase14PlaybackPipeline& pipeline,ts::WavStreamReader& golden,
                 std::size_t frame,bool cached,const std::filesystem::path& path) {
    if (cached) pipeline.startFromCache(path,frame,16384,std::chrono::seconds(120));
    else pipeline.startAtOutputFrame(frame,16384,std::chrono::seconds(120));
    std::vector<std::vector<float>> scratch(golden.channels(),std::vector<float>(4096));
    std::vector<float*> planes(scratch.size());
    for (std::size_t c=0;c<planes.size();++c) planes[c]=scratch[c].data();
    const std::array<std::size_t,7> blocks={64,128,256,512,1024,2048,4096};
    const auto total=std::min<std::size_t>(16384,golden.frames()-frame);
    for (std::size_t at=0,block=0;at<total;++block) {
        const auto count=std::min(blocks[block%blocks.size()],total-at);
        if (pipeline.pullAudio(planes.data(),count)!=count) throw std::runtime_error("FIFO underrun");
        for (std::size_t c=0;c<planes.size();++c)
            for (std::size_t i=0;i<count;++i)
                if (scratch[c][i]!=golden.sample(c,frame+at+i))
                    throw std::runtime_error("Seek differs from Golden");
        at+=count;
    }
    if (pipeline.statistics().fifoRejectedWrites || pipeline.statistics().underrunFrames)
        throw std::runtime_error("FIFO error");
    pipeline.stop();
}
void verify(const std::filesystem::path& inputPath,const std::filesystem::path& goldenPath,
            const std::filesystem::path& root,bool asyncPlayback) {
    ts::WavStreamReader input(inputPath),golden(goldenPath);
    auto config=frozen(input);
    ts::Phase18PcmCache cache(inputPath,root/"cache",config);
    if (cache.validPath()) throw std::runtime_error("Unexpected initial cache hit");
    ts::Phase14PlaybackPipeline playback(config);
    playback.prepare(inputPath);
    if (asyncPlayback) {
        playback.start();
        if (!playback.waitForPrefill(16384,std::chrono::seconds(120)))
            throw std::runtime_error("Initial DSP prefill failed");
    }
    cache.beginGeneration();
    if (asyncPlayback) {
        std::vector<std::vector<float>> scratch(input.channels(),std::vector<float>(1024));
        std::vector<float*> planes(scratch.size());
        for (std::size_t c=0;c<planes.size();++c) planes[c]=scratch[c].data();
        std::size_t at=0;
        while (at<std::min<std::size_t>(golden.frames(),input.sampleRate()*2)) {
            const auto count=std::min<std::size_t>(1024,golden.frames()-at);
            if (playback.availableOutputFrames()<count) {
                playback.rethrowWorkerError();
                std::this_thread::sleep_for(std::chrono::microseconds(100));
                continue;
            }
            if (playback.pullAudio(planes.data(),count)!=count) throw std::runtime_error("Playback underrun");
            for (std::size_t c=0;c<scratch.size();++c)
                for (std::size_t i=0;i<count;++i)
                    if (scratch[c][i]!=golden.sample(c,at+i))
                        throw std::runtime_error("DSP changed during async cache generation");
            at+=count;
        }
        playback.stop();
    }
    cache.wait();
    if (!cache.generationError().empty()) throw std::runtime_error(cache.generationError());
    auto valid=cache.validPath();
    if (!valid) throw std::runtime_error("Fresh cache invalid");
    compareFiles(*valid,goldenPath);
    const std::array<std::size_t,6> positions={0,golden.frames()/100,golden.frames()/2,
        golden.frames()*9/10,golden.frames()-std::min<std::size_t>(golden.frames(),input.sampleRate()),
        golden.frames()-1};
    for (const auto at:positions) compareSeek(playback,golden,at,true,*valid);
    // Repeated seeks: only the final request needs to be rendered.
    for (const auto at:{golden.frames()*3/4,golden.frames()/4,golden.frames()*4/5})
        compareSeek(playback,golden,at,true,*valid);
    if (asyncPlayback) {
        ts::Phase18SeekQueue requests;
        const auto original=requests.post(golden.frames()*9/10);
        std::thread replace([&] {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            requests.post(golden.frames()/3);
            requests.post(golden.frames()*2/3);
        });
        bool cancelled=false;
        try {
            playback.startAtOutputFrame(golden.frames()*9/10,16384,
                std::chrono::seconds(120),[&] { return requests.superseded(original); });
        } catch (const ts::SeekSuperseded&) {cancelled=true;}
        replace.join();
        playback.stop();
        if (!cancelled) throw std::runtime_error("Old seek was not cancelled");
        const auto [version,last]=requests.latest();
        if (version!=3 || last!=golden.frames()*2/3)
            throw std::runtime_error("Seek queue did not prioritize last request");
        compareSeek(playback,golden,last,true,*valid);
    }
    // Hash mismatch must invalidate a modified file before any cached playback.
    {
        std::fstream corrupt(*valid,std::ios::binary|std::ios::in|std::ios::out);
        corrupt.seekp(44+1024);
        const char changed=0x7f;
        corrupt.write(&changed,1);
    }
    if (cache.validPath()) throw std::runtime_error("Corrupt cache accepted");
    compareSeek(playback,golden,golden.frames()/2,false,*valid);
    if (asyncPlayback) {
        std::fstream changedInput(inputPath,std::ios::binary|std::ios::in|std::ios::out);
        changedInput.seekp(44+64);
        const char altered=0x42;
        changedInput.write(&altered,1);
        changedInput.close();
        bool rejected=false;
        try { (void)cache.validPath(); }
        catch (const std::runtime_error&) { rejected=true; }
        if (!rejected) throw std::runtime_error("Input mutation was not rejected");
    }
    std::cout << inputPath.filename().string() << ": golden byte exact, 9 cached seeks exact, "
              << "corruption rejected, fallback exact, generation_seconds="
              << cache.generationSeconds() << '\n';
}
}
int main(int argc,char** argv) {
    std::filesystem::path root;
    try {
        root=tempDirectory();
        if (argc==2) {
            const std::filesystem::path directory(argv[1]);
            for (const char* name:{"mix","vocal","bass","drums","guitar"})
                verify(directory/"input"/(std::string(name)+".wav"),
                       directory/"raw"/(std::string(name)+"_050.wav"),
                       root/name,false);
        } else if (argc==1) {
            constexpr std::size_t frames=48000*3;
            std::array<std::vector<float>,2> data={std::vector<float>(frames),std::vector<float>(frames)};
            for (std::size_t i=0;i<frames;++i) {
                const float tone=0.2f*std::sin(2*3.141592653589793*437.3*i/48000.0);
                data[0][i]=tone+(i==12345?0.7f:0);
                data[1][i]=0.7f*tone+(i==12345?0.5f:0);
            }
            const auto inputPath=root/"test.wav",goldenPath=root/"golden.wav";
            const float* planes[]={data[0].data(),data[1].data()};
            ts::WavStreamWriter writer(inputPath,48000,2,frames);
            writer.write(planes,frames);writer.finish();
            ts::WavStreamReader input(inputPath);
            ts::WavStreamWriter golden(goldenPath,48000,2,frames*2);
            ts::Phase13StreamingEngine(frozen(input)).processFile(inputPath,
                [&](const float* const* samples,std::size_t count){golden.write(samples,count);});
            golden.finish();
            verify(inputPath,goldenPath,root/"synthetic",true);
        } else throw std::invalid_argument("Usage: phase18_tests [golden_dir]");
        std::filesystem::remove_all(root);
    } catch (const std::exception& error) {
        std::cerr << "Phase 18: " << error.what() << '\n';
        if (!root.empty()) std::filesystem::remove_all(root);
        return 1;
    }
}
