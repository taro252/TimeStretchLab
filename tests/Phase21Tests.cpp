#include "audio/WavStream.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TransientEventMap.h"
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
bool identical(const std::filesystem::path& a, const std::filesystem::path& b) {
    std::ifstream left(a,std::ios::binary),right(b,std::ios::binary);
    return std::equal(std::istreambuf_iterator<char>(left),std::istreambuf_iterator<char>(),
                      std::istreambuf_iterator<char>(right),std::istreambuf_iterator<char>());
}
ts::StretchConfig config(double speed,std::uint32_t sampleRate=48000) {
    ts::StretchConfig c;
    c.sampleRate=sampleRate;
    c.channels=2;
    c.timeRatio=1.0/speed;
    c.enableMultiResolution=true;
    c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;
    c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
void compareEventMaps(const ts::Phase13TransientAnalysis& analysis,double ratio) {
    const auto& frames=analysis.detectorFrames();
    ts::TransientEventMap oldMap(frames,analysis.activeFrameCount(),1024,ratio);
    ts::TransientEventMap newMap(frames,analysis.activeFrameCount(),1024,ratio,
                                 ts::EventMapConfig{},analysis.events());
    std::vector<double> offsets;
    for (const auto& anchor:analysis.anchors()) offsets.push_back(anchor.sampleOffset);
    oldMap.refineAnchors(offsets);
    newMap.refineAnchors(offsets);
    require(oldMap.starts()==newMap.starts(),"Separated TimeMap differs from legacy");
    require(oldMap.events().size()==newMap.events().size(),"Event count differs");
    for (std::size_t i=0;i<frames.size();++i)
        require(oldMap.resetAt(i)==newMap.resetAt(i),"Reset list differs");
    for (std::size_t i=0;i<oldMap.events().size();++i) {
        const auto& a=oldMap.events()[i];
        const auto& b=newMap.events()[i];
        require(a.onsetFrame==b.onsetFrame && a.peakFrame==b.peakFrame &&
                a.attackEndFrame==b.attackEndFrame && a.endFrame==b.endFrame &&
                a.strength==b.strength,"Event list differs");
    }
}
void realGolden(const std::filesystem::path& root,const std::filesystem::path& scratch) {
    for (const char* name:{"mix","vocal","bass","drums","guitar"}) {
        const auto input=root/"results/phase12/golden/input"/(std::string(name)+".wav");
        ts::WavStreamReader reader(input);
        auto halfConfig=config(0.50,reader.sampleRate());
        halfConfig.channels=static_cast<int>(reader.channels());
        ts::Phase13StreamingEngine half(halfConfig);
        const auto analysis=half.analyzeTransientEvents(input);
        for (double speed:{0.50,0.75}) {
            auto c=config(speed,reader.sampleRate());
            c.channels=static_cast<int>(reader.channels());
            ts::Phase13StreamingEngine engine(c);
            compareEventMaps(analysis,c.timeRatio);
            const auto prepared=engine.prepareWithAnalysis(analysis);
            const auto suffix=speed==0.50 ? "_050.wav" : "_075.wav";
            const auto reference=root/"results/phase12/golden/raw"/(std::string(name)+suffix);
            const auto output=scratch/(std::string(name)+suffix);
            ts::WavStreamWriter writer(output,reader.sampleRate(),reader.channels(),
                                      prepared.outputFrames());
            const auto result=engine.processPrepared(prepared,
                [&](const float* const* data,std::size_t count) { writer.write(data,count); },16384);
            writer.finish();
            require(result.processing.outputFrames==prepared.outputFrames(),"Golden length differs");
            require(identical(reference,output),"Golden WAV bytes differ");
            std::cout<<name<<','<<speed<<','<<analysis.events().size()<<','
                     <<result.processing.timeMapHash<<",byte-identical\n";
        }
    }
}
}
int main(int argc,char** argv) {
    const auto dir=std::filesystem::temp_directory_path()/
        ("phase21_test_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(dir);
    try {
        constexpr std::size_t frames=96000;
        std::array<std::vector<float>,2> samples={std::vector<float>(frames),std::vector<float>(frames)};
        for (std::size_t i=0;i<frames;++i) {
            const auto click=(i%24000==10000) ? 0.8f : 0.0f;
            samples[0][i]=click;
            samples[1][i]=click;
        }
        const float* pointers[]={samples[0].data(),samples[1].data()};
        const auto input=dir/"click.wav";
        {
            ts::WavStreamWriter writer(input,48000,2,frames);
            writer.write(pointers,frames);
            writer.finish();
        }
        ts::Phase13StreamingEngine half(config(0.50)),threeQuarter(config(0.75));
        const auto analysis=half.analyzeTransientEvents(input);
        require(analysis.inputFrames()==frames,"Input analysis length wrong");
        require(!analysis.events().empty(),"Artificial clicks not detected");
        std::size_t confidentAnchors=0;
        for (const auto& anchor:analysis.anchors())
            if (anchor.confident) ++confidentAnchors;
        require(confidentAnchors>0,"Artificial clicks did not exercise precise anchors");
        for (double ratio:{2.0,4.0/3.0}) compareEventMaps(analysis,ratio);
        for (double speed:{0.50,0.75}) {
            auto c=config(speed);
            auto& engine=speed==0.50 ? half : threeQuarter;
            const auto prepared=engine.prepareWithAnalysis(analysis);
            const auto expected=static_cast<std::size_t>(std::round(frames*c.timeRatio));
            require(prepared.outputFrames()==expected,"Output length wrong");
            const auto offline=dir/(speed==0.50 ? "offline050.wav" : "offline075.wav");
            const auto reference=ts::ChunkedTimeStretchEngine(c).processWav(input,offline,8192);
            std::array<ts::Phase13Result,2> results;
            for (int n=0;n<2;++n) {
                const auto output=dir/(speed==0.50
                    ? (n==0 ? "stream050_8192.wav":"stream050_16384.wav")
                    : (n==0 ? "stream075_8192.wav":"stream075_16384.wav"));
                ts::WavStreamWriter writer(output,48000,2,expected);
                results[n]=engine.processPrepared(prepared,
                    [&](const float* const* data,std::size_t count) { writer.write(data,count); },
                    n==0 ? 8192 : 16384);
                writer.finish();
                require(identical(offline,output),"Streaming WAV differs from offline");
                require(results[n].processing.outputFrames==expected,"Streaming EOS length wrong");
                require(results[n].processing.timeMapHash==reference.timeMapHash,"TimeMap hash differs");
            }
            require(results[0].stages.fft==results[1].stages.fft,"FFT block dependence");
            require(results[0].stages.phase==results[1].stages.phase,"Phase block dependence");
            require(results[0].stages.ifft==results[1].stages.ifft,"IFFT block dependence");
            require(results[0].stages.ola==results[1].stages.ola,"OLA block dependence");
            require(results[0].stages.lowFir==results[1].stages.lowFir,"Low FIR block dependence");
            require(results[0].stages.highFir==results[1].stages.highFir,"High FIR block dependence");
            require(results[0].stages.fir==results[1].stages.fir,"Output FIR block dependence");
        }
        if (argc==2) realGolden(argv[1],dir);
        std::filesystem::remove_all(dir);
        std::cout<<"Phase 21: 0.50/0.75 events, resets, maps, raw WAV and stage digests match"
                 <<" (click events="<<analysis.events().size()
                 <<", confident anchors="<<confidentAnchors<<")\n";
    } catch (const std::exception& e) {
        std::cerr<<e.what()<<" (files: "<<dir<<")\n";
        return 1;
    }
}
