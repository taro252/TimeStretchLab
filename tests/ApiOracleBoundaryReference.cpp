// Independent boundary equation only. No product headers, library, DSP or audio.
// Build with the SAME compiler/config/FP contraction settings as the product.
#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
static void need(bool v,const char* reason){if(!v)throw std::runtime_error(reason);}
static float tail(float value,float last,float first,std::size_t j,std::size_t n){
    if(j+1==n)return last*.5f+first*.5f;
    const float t=float(j+1)/float(n);return value-(last-first)*.5f*(t*t*(3.f-2.f*t));
}
static float head(float value,float last,float first,std::size_t j,std::size_t n){
    if(!j)return last*.5f+first*.5f;
    const float t=1.f-float(j)/float(n);return value+(last-first)*.5f*(t*t*(3.f-2.f*t));
}
int main(int argc,char** argv){try{
    need(argc==6,"RAW_BASE JOINS_CSV CHANNELS FRAMES NEW_REFERENCE_RAW");
    const auto channels=std::stoull(argv[3]),frames=std::stoull(argv[4]);
    need(channels&&channels<=2&&frames&&frames<=256ULL*1024*1024/(channels*sizeof(float)),"bounded positive mono/stereo fixture required");
    std::vector<float> values(frames*channels);std::ifstream raw(argv[1],std::ios::binary);
    need(bool(raw.read(reinterpret_cast<char*>(values.data()),values.size()*sizeof(float))),"base RAW truncated");char extra=0;need(!raw.read(&extra,1),"base RAW has extra frames");
    for(float v:values)need(std::isfinite(v),"base RAW nonfinite");
    std::ifstream joins(argv[2]);need(bool(joins),"joins absent");std::string line;std::getline(joins,line);
    need(line=="boundary,old_n,new_n,channel,last_bits,first_bits","join schema");
    std::size_t count=0;unsigned long long previousBoundary=0,previousOld=0,previousNew=0;
    while(std::getline(joins,line)){
        std::istringstream in(line);std::vector<unsigned long long> row;std::string cell;
        while(std::getline(in,cell,','))row.push_back(std::stoull(cell));
        need(row.size()==6&&row[0]<=frames&&row[1]&&row[1]<=4096&&row[2]&&row[2]<=4096&&row[3]<channels&&++count<=128,"join bounds");
        const auto boundary=static_cast<long long>(row[0]);
        const std::size_t oldN=row[1],newN=row[2],channel=row[3];
        need(row[4]<=UINT32_MAX&&row[5]<=UINT32_MAX,"join float bits overflow");
        need(channel==(count-1)%channels,"join channel order/duplicate");
        if(!channel){need(!previousBoundary||row[0]>previousBoundary,"join boundary order/duplicate");previousBoundary=row[0];previousOld=row[1];previousNew=row[2];}
        else need(row[0]==previousBoundary&&row[1]==previousOld&&row[2]==previousNew,"join channel group differs");
        const auto last=std::bit_cast<float>(std::uint32_t(row[4])),first=std::bit_cast<float>(std::uint32_t(row[5]));
        need(std::isfinite(last)&&std::isfinite(first),"join endpoint nonfinite");
        for(std::size_t j=0;j<oldN;++j){const auto at=boundary-static_cast<long long>(oldN)+static_cast<long long>(j);
            if(at>=0&&std::uint64_t(at)<frames)values[std::size_t(at)*channels+channel]=tail(values[std::size_t(at)*channels+channel],last,first,j,oldN);}
        for(std::size_t j=0;j<newN&&std::uint64_t(boundary)+j<frames;++j){const auto at=std::size_t(boundary)+j;
            values[at*channels+channel]=head(values[at*channels+channel],last,first,j,newN);}
    }
    need(joins.eof()&&count&&count%channels==0,"empty/incomplete joins");
    for(float v:values)need(std::isfinite(v),"processed reference nonfinite");
    std::ofstream output(argv[5],std::ios::binary);output.write(reinterpret_cast<const char*>(values.data()),values.size()*sizeof(float));need(bool(output),"reference write failed");
    std::cout<<"{\"suite\":\"independent_boundary_equation\",\"expected\":1,\"executed\":1,\"status\":\"PASS\",\"frames\":"<<frames<<",\"channels\":"<<channels<<",\"joins\":"<<count/channels<<",\"nonfinite\":0}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';std::cout<<"{\"suite\":\"independent_boundary_equation\",\"expected\":1,\"executed\":0,\"status\":\"FAIL\"}\n";return 2;}}
