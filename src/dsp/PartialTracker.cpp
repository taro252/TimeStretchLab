#include "dsp/PartialTracker.h"
#include "dsp/PhaseVocoder.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace ts {
namespace {
constexpr double twoPi=2*std::numbers::pi;
double wrap(double phase) { return std::remainder(phase,twoPi); }
}

PartialTracker::PartialTracker(std::size_t fftSize,int analysisHop,double sampleRate,int channels)
    : fftSize_(fftSize),binCount_(fftSize/2+1),analysisHop_(analysisHop),
      channels_(channels),sampleRate_(sampleRate),tracks_(binCount_),
      trackForPeakBin_(binCount_,-1),previousPeakIds_(binCount_,-1),
      currentPeakIds_(binCount_,-1) {
    if (fftSize<16 || analysisHop<1 || !std::isfinite(sampleRate) || sampleRate<=0 ||
        (channels!=1 && channels!=2))
        throw std::invalid_argument("Invalid PartialTracker configuration");
    activeIndices_.reserve(binCount_);
}
void PartialTracker::reset(bool countLifetimes) {
    for (auto& track:tracks_) {
        if (track.active && countLifetimes) {
            stats_.finishedLifetimeFrames+=track.age;
            ++stats_.finishedTracks;
        }
        track.active=false;
    }
    std::fill(trackForPeakBin_.begin(),trackForPeakBin_.end(),-1);
    std::fill(previousPeakIds_.begin(),previousPeakIds_.end(),-1);
    activeIndices_.clear();
}
bool PartialTracker::eligible(const SpectralPeak& peak,const PhaseLocker& map,float frameMax) const {
    const double frequency=peak.position*sampleRate_/fftSize_;
    if (frequency<150 || frequency>6000 || peak.magnitude<1e-7f) return false;
    const auto& magnitude=map.magnitudes();
    if (peak.magnitude<0.01*frameMax) return false;
    double local=0;
    int count=0;
    for (int offset=-8;offset<=8;++offset) {
        const int bin=peak.bin+offset;
        if (bin<1 || bin>=static_cast<int>(binCount_-1)) continue;
        local+=magnitude[bin];
        ++count;
    }
    return count && peak.magnitude/(local/count+1e-12)>=3.0;
}
int PartialTracker::findMatch(float frequencyHz,float magnitude) const {
    int best=-1;
    double bestCost=std::numeric_limits<double>::infinity();
    for (const int i:activeIndices_) {
        const auto& track=tracks_[i];
        if (!track.active || track.matched || track.missedFrames>2) continue;
        const double cents=std::abs(1200*std::log2(double(frequencyHz)/track.frequencyHz));
        const double hz=std::abs(double(frequencyHz)-track.frequencyHz);
        if (cents>80 || hz>1.5*sampleRate_/fftSize_) continue;
        const double magnitudePenalty=std::abs(std::log((double(magnitude)+1e-7)/
                                                          (track.magnitude+1e-7)));
        const double cost=cents/80+hz/(1.5*sampleRate_/fftSize_)+0.25*magnitudePenalty+
                          0.12*track.missedFrames;
        if (cost<bestCost) { bestCost=cost; best=i; }
    }
    return best;
}
int PartialTracker::acquireSlot() {
    for (std::size_t i=0;i<tracks_.size();++i)
        if (!tracks_[i].active) return static_cast<int>(i);
    return -1;
}
void PartialTracker::process(const PhaseLocker& peaks,
    const std::array<const std::complex<float>*,2>& input,
    const std::array<std::complex<float>*,2>& output,
    const std::array<PhaseVocoder*,2>& vocoders,
    double synthesisHop,bool resetPhase) {
    if (resetPhase) reset();
    std::fill(trackForPeakBin_.begin(),trackForPeakBin_.end(),-1);
    std::fill(currentPeakIds_.begin(),currentPeakIds_.end(),-1);
    activeIndices_.clear();
    for (std::size_t i=0;i<tracks_.size();++i) if (tracks_[i].active) {
        tracks_[i].matched=false;
        activeIndices_.push_back(static_cast<int>(i));
    }
    const auto& magnitudes=peaks.magnitudes();
    const float frameMax=*std::max_element(magnitudes.begin(),magnitudes.end());
    for (const auto& peak:peaks.peaks()) {
        if (!eligible(peak,peaks,frameMax)) continue;
        ++stats_.trackablePeakFrames;
        const float frequency=peak.position*sampleRate_/fftSize_;
        int index=findMatch(frequency,peak.magnitude);
        const bool matched=index>=0;
        if (!matched) {
            const int first=std::max(1,peak.bin-2);
            const int last=std::min(static_cast<int>(binCount_)-2,peak.bin+2);
            for (int bin=first;bin<=last;++bin) if (previousPeakIds_[bin]>=0) {
                ++stats_.trackSwitches;
                break;
            }
            index=acquireSlot();
            if (index<0) continue;
            tracks_[index]=TrackedPeak{};
            tracks_[index].active=true;
            tracks_[index].trackId=nextId_++;
            activeIndices_.push_back(index);
            ++stats_.births;
        } else ++stats_.matchedPeakFrames;
        auto& track=tracks_[index];
        const int oldBin=track.bin;
        const int missed=track.missedFrames;
        const double hopDistance=synthesisHop+track.pendingSynthesisHop;
        for (int channel=0;channel<channels_;++channel) {
            auto& state=track.channel[channel];
            const double peakMagnitude=std::abs(input[channel][peak.bin]);
            if (peakMagnitude<1e-7) { state.valid=false; continue; }
            double omega=twoPi*frequency/sampleRate_;
            double migrationPhase=0;
            const bool oldBinUsable=matched && missed==0 && oldBin>0 &&
                std::abs(input[channel][oldBin])>=std::max(1e-7,0.05*peakMagnitude);
            if (matched && state.valid && missed==0 && oldBin>0 &&
                oldBinUsable) {
                const double binOmega=twoPi*oldBin/fftSize_;
                const double currentPhase=std::arg(input[channel][oldBin]);
                const double residual=wrap(currentPhase-state.previousAnalysisPhase-
                                           binOmega*analysisHop_);
                const double estimated=binOmega+residual/analysisHop_;
                if (std::abs((estimated-omega)*sampleRate_/twoPi)<=
                    1.5*sampleRate_/fftSize_) omega=estimated;
                // The old-bin estimate predicts the old bin in the current
                // frame. Transfer its phase to the new peak bin at this frame.
                if (oldBin!=peak.bin)
                    migrationPhase=wrap(double(std::arg(input[channel][peak.bin]))-
                                        currentPhase);
            }
            if (matched && state.valid) {
                const double previous=state.synthesisPhase;
                state.synthesisPhase=wrap(previous+omega*hopDistance+migrationPhase);
                const double error=std::abs(wrap(state.synthesisPhase-previous-
                                                 omega*hopDistance-migrationPhase));
                stats_.phaseDiscontinuitySum+=error;
                stats_.phaseDiscontinuityMax=std::max(stats_.phaseDiscontinuityMax,error);
                ++stats_.phaseDiscontinuityCount;
            } else state.synthesisPhase=std::arg(output[channel][peak.bin]);
            state.angularFrequency=omega;
            state.previousAnalysisPhase=std::arg(input[channel][peak.bin]);
            state.valid=true;
        }
        track.bin=peak.bin;
        track.interpolatedBin=peak.position;
        track.magnitude=peak.magnitude;
        track.frequencyHz=frequency;
        track.age+=1;
        track.missedFrames=0;
        track.pendingSynthesisHop=0;
        track.matched=true;
        trackForPeakBin_[peak.bin]=index;
        currentPeakIds_[peak.bin]=track.trackId;
        if (track.age>=3) ++stats_.appliedPeakFrames;
    }
    std::size_t active=0;
    for (auto& track:tracks_) if (track.active) {
        if (!track.matched) {
            track.pendingSynthesisHop+=synthesisHop;
            if (++track.missedFrames>2) {
                stats_.finishedLifetimeFrames+=track.age;
                ++stats_.finishedTracks;
                track.active=false;
                continue;
            }
        }
        ++active;
    }
    ++stats_.processedFrames;
    stats_.activeTrackFrames+=active;
    previousPeakIds_=currentPeakIds_;
    const auto& owners=peaks.ownerPeak();
    for (std::size_t bin=1;bin+1<binCount_;++bin) {
        const int owner=owners[bin];
        if (owner<1 || static_cast<std::size_t>(owner)>=trackForPeakBin_.size()) continue;
        const int trackIndex=trackForPeakBin_[owner];
        if (trackIndex<0 || tracks_[trackIndex].age<3 || magnitudes[bin]<1e-7f ||
            magnitudes[bin]<0.001*frameMax) continue;
        const auto& track=tracks_[trackIndex];
        for (int channel=0;channel<channels_;++channel) {
            if (!track.channel[channel].valid || std::abs(input[channel][bin])<1e-7f ||
                std::abs(input[channel][owner])<1e-7f) continue;
            const double relative=wrap(double(std::arg(input[channel][bin]))-
                                       std::arg(input[channel][owner]));
            const double phase=wrap(track.channel[channel].synthesisPhase+relative);
            output[channel][bin]=std::polar(std::abs(input[channel][bin]),
                                            static_cast<float>(phase));
            vocoders[channel]->setOutputPhase(bin,phase);
        }
    }
}
void PartialTracker::synchronize(const std::array<std::complex<float>*,2>& output) {
    for (const int index:trackForPeakBin_) if (index>=0) {
        auto& track=tracks_[index];
        for (int c=0;c<channels_;++c) if (track.channel[c].valid &&
            std::abs(output[c][track.bin])>=1e-7f)
            track.channel[c].synthesisPhase=std::arg(output[c][track.bin]);
    }
}
int PartialTracker::trackIdForBin(std::size_t bin) const {
    if (bin>=trackForPeakBin_.size() || trackForPeakBin_[bin]<0) return -1;
    return tracks_[trackForPeakBin_[bin]].trackId;
}
double PartialTracker::averageLifetimeFrames() const {
    double sum=stats_.finishedLifetimeFrames;
    std::size_t count=stats_.finishedTracks;
    for (const auto& track:tracks_) if (track.active) { sum+=track.age; ++count; }
    return count ? sum/count : 0;
}
double PartialTracker::averageTrackCount() const {
    return stats_.processedFrames ? double(stats_.activeTrackFrames)/stats_.processedFrames : 0;
}
double PartialTracker::continuityRatio() const {
    return stats_.trackablePeakFrames ?
        double(stats_.matchedPeakFrames)/stats_.trackablePeakFrames : 0;
}
}
