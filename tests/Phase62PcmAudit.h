#pragma once
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <array>
#include <atomic>
#include <cmath>
// Host-owned, fixed storage; only one callback writer. Inspect after quiescence.
struct LoopPcmAudit {
    struct Raw {std::uint64_t epoch=0;std::size_t next=0;std::array<std::array<float,8192>,2> pcm{};};
    std::array<Raw,4> raw{};
    std::size_t channels=0;std::uint64_t clock=0,frames=0,mixed=0,errors=0,nonfinite=0,zeroFrames=0;
    explicit LoopPcmAudit(std::size_t c):channels(c){}
    static void source(void* context,const float*const* p,std::size_t n,std::size_t at,std::uint64_t,std::uint64_t epoch,std::uint64_t)noexcept{
        auto& a=*static_cast<LoopPcmAudit*>(context);Raw* r=nullptr;
        for(auto& slot:a.raw)if(slot.epoch==epoch)r=&slot;
        if(!r){r=&a.raw[0];for(auto& slot:a.raw)if(slot.epoch<r->epoch)r=&slot;r->epoch=epoch;r->next=at;}
        if(r->next!=at)++a.errors;
        for(std::size_t c=0;c<a.channels;++c)for(std::size_t i=0;i<n;++i)r->pcm[c][(at+i)%8192]=p[c][i];r->next=at+n;
    }
    static void output(void* context,const float*const* p,const ts::playback::ProgressiveOutputSpan& span)noexcept{
        auto& a=*static_cast<LoopPcmAudit*>(context);if(span.callbackFrame!=a.clock)++a.errors;a.clock=span.callbackFrame+span.frames;
        const Raw* fresh=nullptr;const Raw* old=nullptr;for(const auto& r:a.raw){if(r.epoch==span.newEpoch)fresh=&r;if(r.epoch==span.oldEpoch)old=&r;}
        for(std::size_t i=0;i<span.frames;++i){bool zero=true;for(std::size_t c=0;c<a.channels;++c){
            float expected=fresh&&i<span.newReceivedFrames?fresh->pcm[c][(span.newOutputOffset+i)%8192]:0.f;
            if(i<span.mixedFrames){const float prev=old&&i<span.oldReceivedFrames?old->pcm[c][(span.oldOutputOffset+i)%8192]:0.f;
                const auto gain=float(span.transitionOffset+i+1)/float(span.transitionLength);expected=prev*(1.f-gain)+expected*gain;}
            if(p[c][i]!=expected)++a.errors;if(!std::isfinite(p[c][i]))++a.nonfinite;zero&=p[c][i]==0;
        }a.zeroFrames+=zero;}
        a.frames+=span.frames;a.mixed+=span.mixedFrames;
    }
};
