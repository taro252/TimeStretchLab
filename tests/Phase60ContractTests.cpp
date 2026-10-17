#include "playback/ProgressiveContract.h"
#include <iostream>
#include <limits>
using namespace ts::playback::progressive;
void require(bool v){if(!v)throw std::runtime_error("Phase60 contract assertion");}
int main(){try{
    for(unsigned p=40;p<=200;++p)require(speedMicros(p/100.)==p*10000);
    for(double s:{.399,2.01,.405,1.001,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()}){bool rejected=false;try{speedMicros(s);}catch(const std::invalid_argument&){rejected=true;}require(rejected);}
    require(!Capabilities{}.seek&&Capabilities{}.maxConcurrentSessions==1);
    require(reservationBytes(1024,48000)>256*1024*1024);
    for(auto bounds:{std::pair<std::uint64_t,std::uint64_t>{0,1},{512ULL*1024*1024+1,1},{1,48000ULL*600+1}}){bool rejected=false;try{reservationBytes(bounds.first,bounds.second);}catch(const std::length_error&){rejected=true;}require(rejected);}
    require(!SupplyQuality::evaluate(0,0,0).failed);
    require(SupplyQuality::evaluate(1,0,0).failed&&SupplyQuality::evaluate(0,1,0).failed&&SupplyQuality::evaluate(0,0,1).failed);
    std::cout<<"PASS 161 speeds, invalid grid, budgets, capability, supply != lifecycle\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
