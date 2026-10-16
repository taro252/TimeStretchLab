#include "prototype/Phase35PhaseVocoder.h"
#include "reference/phase59_fix/Before59FixPhaseVocoder.h"
#include "audio/WavReader.h"
#include "dsp/STFT.h"
#include <chrono>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;
namespace {
double cpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
struct Result{double wall,cpu;std::vector<std::complex<float>> output;};
template<class Vocoder> Result measure(std::size_t size,std::uint32_t rate,const std::vector<std::vector<std::complex<float>>>& spectra,const std::vector<std::vector<int>>& owners){
    Vocoder vocoder(size,int(size/4),true,rate);std::vector<std::complex<float>> output(size/2+1);
    const auto start=std::chrono::steady_clock::now();const auto began=cpu();
    for(unsigned repeat=0;repeat<20;++repeat)for(std::size_t frame=0;frame<spectra.size();++frame)
        vocoder.process(spectra[frame].data(),output.data(),size/8.,frame%13==0,true,.73f,&owners[frame]);
    const auto cost=cpu()-began;return {std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count(),cost,std::move(output)};
}
}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::invalid_argument("input WAV");const auto input=WavReader::read(argv[1]);
    std::cout<<"fft,round,frames,old_wall_s,old_cpu_s,new_wall_s,new_cpu_s,bit_exact\n"<<std::setprecision(17);
    for(const std::size_t size:{8192,4096,1024}){
        STFT stft(size);PhaseLocker locker(size);std::vector<float> frame(size);
        std::vector<std::vector<std::complex<float>>> spectra;std::vector<std::vector<int>> owners;
        for(const std::size_t center:{684032,6389760,6877184})for(int offset=-4;offset<=4;++offset){
            const auto begin=static_cast<long long>(center)+offset*static_cast<long long>(size/4)-static_cast<long long>(size/2);
            for(std::size_t i=0;i<size;++i){const auto index=begin+static_cast<long long>(i);frame[i]=index>=0&&std::size_t(index)<input.channels[0].size()?input.channels[0][std::size_t(index)]:0;}
            spectra.emplace_back(size/2+1);stft.analyze(frame.data(),spectra.back().data());
            locker.analyzePeaks(spectra.back().data(),size/2+1);owners.push_back(locker.ownerPeak());
        }
        for(unsigned round=0;round<5;++round){
            Result old{},now{};
            if(round%2){now=measure<Phase35PhaseVocoder>(size,input.sampleRate,spectra,owners);old=measure<Before59FixPhaseVocoder>(size,input.sampleRate,spectra,owners);}
            else{old=measure<Before59FixPhaseVocoder>(size,input.sampleRate,spectra,owners);now=measure<Phase35PhaseVocoder>(size,input.sampleRate,spectra,owners);}
            const bool exact=old.output.size()==now.output.size()&&std::memcmp(old.output.data(),now.output.data(),old.output.size()*sizeof(old.output[0]))==0;
            std::cout<<size<<','<<round<<','<<spectra.size()*20<<','<<old.wall<<','<<old.cpu<<','<<now.wall<<','<<now.cpu<<','<<exact<<'\n';
            if(!exact)throw std::runtime_error("Benchmark final output differs");
        }
    }
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
