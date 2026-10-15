// Counterexamples use the existing event grouper/map, not a reimplementation.
#include "dsp/TransientEventMap.h"
#include <iostream>
#include <stdexcept>
using namespace ts;
void check(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);}
TransientFrame candidate(double flux){return {flux,10,1,.02,1,true,false};}
int main(){try{
    // Every candidate is within four frames of the previous one. No fixed
    // lookahead can seal this event while the chain continues.
    for(std::size_t horizon:{16,128,4096}) {
        std::vector<TransientFrame> frames(horizon+32);
        for(std::size_t i=4;i<horizon;i+=4)
            frames[i]=candidate(.25+.5*double(i)/double(horizon+4));
        auto before=TransientEventMap::consolidateEvents(frames,horizon);
        frames[horizon]=candidate(.25+.5*double(horizon)/double(horizon+4));
        auto after=TransientEventMap::consolidateEvents(frames,horizon+1);
        check(before.size()==1&&after.size()==1,"Chain should remain one event");
        check(before[0].onsetFrame==after[0].onsetFrame&&before[0].peakFrame!=after[0].peakFrame,"Unsealed peak must be mutable");
    }
    // Equal total file length, equal analysed prefix, different unseen first
    // event: even the first output hop can differ. Knowing EOS is insufficient.
    std::vector<TransientFrame> a(2048),b(2048);
    a[500]=candidate(1);b[1000]=candidate(1);
    TransientEventMap ma(a,a.size()-3,1024,2.),mb(b,b.size()-3,1024,2.);
    check(ma.starts()[1]!=mb.starts()[1],"Future first peak must change node 1");
    // After a closed first peak, the next segment still depends on the next
    // peak. Only intervals bounded by sealed peaks may be committed.
    a[10]=b[10]=candidate(1);
    TransientEventMap ca(a,a.size()-3,1024,2.),cb(b,b.size()-3,1024,2.);
    for(std::size_t i=0;i<=10;++i)check(ca.starts()[i]==cb.starts()[i],"Closed first interval changed");
    std::size_t firstOpenDifference=11;
    while(firstOpenDifference<500&&ca.starts()[firstOpenDifference]==cb.starts()[firstOpenDifference])++firstOpenDifference;
    check(firstOpenDifference<500,"Open next interval must depend on future");
    // finalize() is a one-shot API. At the current last frame a provisional
    // maximum is detected; after appending a stronger next frame it is not.
    // Reusing finalize() leaves old bool flags set; compare with a fresh run.
    TransientConfig cfg;TransientDetector reused(8,cfg),fresh(8,cfg);
    float quiet[8]{},small[8]{0,.1f,.1f,.1f,.1f,.1f,.1f,0};
    float middle[8]{0,.2f,.2f,.2f,.2f,.2f,.2f,0},large[8]{0,10,10,10,10,10,10,0};
    for(auto* detector:{&reused,&fresh}) {
        detector->pushMagnitudes(quiet);
        for(int i=0;i<8;++i)detector->pushMagnitudes(small);
        detector->pushMagnitudes(middle);
    }
    reused.finalize();
    reused.pushMagnitudes(large);reused.finalize();
    fresh.pushMagnitudes(large);fresh.finalize();
    check(reused.frames()[9].detected&&!fresh.frames()[9].detected,"Expected stale finalize flag counterexample");
    std::cout<<"Unbounded event chain, future-dependent node 1/"<<firstOpenDifference<<", sealed segment, one-shot finalize PASS\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
