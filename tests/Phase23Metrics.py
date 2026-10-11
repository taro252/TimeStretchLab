#!/usr/bin/env python3
"""Phase 23 read-only WAV and stage diagnostics (requires NumPy)."""
import csv
from pathlib import Path
import sys

import numpy as np


def details(path):
    size=path.stat().st_size
    if (size-44)%8:
        raise ValueError(f"Unexpected stereo float32 WAV length: {path}")
    return np.memmap(path,dtype="<f4",mode="r",offset=44,shape=((size-44)//8,2))


def properties(audio):
    left=np.asarray(audio[:,0],dtype=np.float64)
    right=np.asarray(audio[:,1],dtype=np.float64)
    mid=(left+right)*0.5
    side=(left-right)*0.5
    midRms=np.sqrt(np.mean(mid*mid))
    sideRms=np.sqrt(np.mean(side*side))
    corr=np.corrcoef(left,right)[0,1] if np.std(left)>1e-9 and np.std(right)>1e-9 else 0.0
    return float(corr),float(sideRms/max(midRms,1e-12))


def spectrum_metrics(audio,rate):
    mono=np.asarray(np.mean(audio,axis=1),dtype=np.float64)
    size=4096
    if len(mono)<size*2:
        return (float("nan"),float("nan"))
    spectra=[]
    for pos in range(0,len(mono)-size+1,1024):
        spectrum=np.abs(np.fft.rfft(mono[pos:pos+size]*np.hanning(size)))
        spectra.append(np.log(np.maximum(spectrum,1e-7)))
    differences=np.sqrt(np.mean(np.diff(np.array(spectra),axis=0)**2,axis=1))
    return float(np.median(differences)),float(np.percentile(differences,90))


def stereo_spectral_metrics(audio):
    size=4096
    if len(audio)<size:
        return float("nan"),float("nan")
    window=np.hanning(size)
    ipdSum=ildSum=weightSum=0.0
    for pos in range(0,len(audio)-size+1,2048):
        left=np.fft.rfft(np.asarray(audio[pos:pos+size,0],dtype=np.float64)*window)
        right=np.fft.rfft(np.asarray(audio[pos:pos+size,1],dtype=np.float64)*window)
        leftMagnitude=np.abs(left)
        rightMagnitude=np.abs(right)
        magnitude=np.minimum(leftMagnitude,rightMagnitude)
        threshold=max(float(np.max(magnitude))*0.01,1e-10)
        valid=magnitude>threshold
        if not np.any(valid):
            continue
        weights=magnitude[valid]**2
        ipd=np.angle(left[valid]*np.conj(right[valid]))
        ild=20*np.log10(np.maximum(leftMagnitude[valid],1e-12)/
                        np.maximum(rightMagnitude[valid],1e-12))
        ipdSum+=float(np.sum(weights*ipd*ipd))
        ildSum+=float(np.sum(weights*ild*ild))
        weightSum+=float(np.sum(weights))
    return (float(np.sqrt(ipdSum/weightSum)),float(np.sqrt(ildSum/weightSum))) \
        if weightSum else (float("nan"),float("nan"))


def sine_frequency(audio,rate):
    signal=np.asarray(np.mean(audio,axis=1),dtype=np.float64)
    window=np.hanning(len(signal))
    power=np.abs(np.fft.rfft(signal*window))
    peak=int(np.argmax(power[1:]))+1
    if peak==len(power)-1:
        return float("nan")
    left,center,right=np.log(np.maximum(power[peak-1:peak+2],1e-20))
    offset=0.5*(left-right)/(left-2*center+right)
    return float((peak+offset)*rate/len(signal))


def click_attacks(audio,rate):
    envelope=np.max(np.abs(audio),axis=1)
    candidates=np.flatnonzero((envelope>0.1)&
                              (envelope>=np.roll(envelope,1))&
                              (envelope>np.roll(envelope,-1)))
    groups=[]
    for index in candidates:
        if not groups or index-groups[-1][-1]>rate//10:
            groups.append([int(index)])
        else:
            groups[-1].append(int(index))
    attacks=[]
    for group in groups:
        index=max(group,key=lambda position:envelope[position])
        height=float(envelope[index])
        left=right=index
        while left>0 and envelope[left-1]>=height*0.5:
            left-=1
        while right+1<len(envelope) and envelope[right+1]>=height*0.5:
            right+=1
        attacks.append((index,height,right-left+1))
    return attacks


def unexpected_silence(audio,rate):
    width=max(1,rate//100)
    mono=np.asarray(audio,dtype=np.float64)
    levels=[]
    for start in range(0,len(mono)-width+1,width):
        piece=mono[start:start+width]
        levels.append(float(np.sqrt(np.mean(piece*piece))))
    return sum(levels[i]<1e-7 and levels[i-1]>1e-3 and levels[i+1]>1e-3
               for i in range(1,len(levels)-1))


def local_attack(audio,center,rate):
    envelope=np.max(np.abs(audio),axis=1)
    left=max(0,center-rate//20)
    right=min(len(envelope),center+rate//20)
    index=left+int(np.argmax(envelope[left:right]))
    height=float(envelope[index])
    start=end=index
    while start>0 and envelope[start-1]>=height*0.5:
        start-=1
    while end+1<len(envelope) and envelope[end+1]>=height*0.5:
        end+=1
    return index,height,end-start+1


def stage_comparison(directory,name):
    def load(mode):
        path=directory/f"{name}_{mode}.stages.csv"
        with path.open() as stream:
            rows=list(csv.DictReader(stream))
        return rows
    fixedRows=load("050")
    switchedRows=load("switch")
    fixed={(r["resolution"],r["frame"]):r for r in fixedRows if r["stage"]=="frame"}
    switched={(r["resolution"],r["frame"]):r for r in switchedRows if r["stage"]=="frame"}
    out=[]
    for resolution in ("0","1","2"):
        common=sorted((int(frame) for r,frame in fixed.keys()
                       if r==resolution and (r,frame) in switched))
        first={}
        for field in ("fft","phase","ifft","ola"):
            mismatch=next((frame for frame in common
                           if fixed[(resolution,str(frame))][field]!=
                           switched[(resolution,str(frame))][field]),None)
            first[field]=mismatch
        out.append((resolution,len(common),first))
    fixedFir={r["output_sample"]:r for r in fixedRows if r["stage"]=="fir"}
    switchFir={r["output_sample"]:r for r in switchedRows if r["stage"]=="fir"}
    common=sorted((int(sample) for sample in fixedFir if sample in switchFir))
    fir={}
    for field in ("low_fir","high_fir","output_fir"):
        fir[field]=next((sample for sample in common
                         if fixedFir[str(sample)][field]!=switchFir[str(sample)][field]),-1)
    return out,(len(common),fir)


def main():
    root=Path(sys.argv[1]).resolve()
    target=root/"results/phase23"
    raw=root/"results/phase12/golden/raw"
    rows=[]
    stages=[]
    firStages=[]
    for name in ("mix","vocal","bass","drums","guitar","click","sine"):
        log=dict(line.split("=",1) for line in
                 (target/"diagnostics"/f"{name}_switch.txt").read_text().splitlines()
                 if "=" in line)
        rate=44100 if name=="mix" else 48000
        switched=details(target/"raw"/f"{name}_switch.wav")
        fixed050=details(raw/f"{name}_050.wav" if name not in ("click","sine")
                         else target/"baseline"/f"{name}_050.wav")
        fixed075=details(raw/f"{name}_075.wav" if name not in ("click","sine")
                         else target/"baseline"/f"{name}_075.wav")
        committed=int(log["committed_output"])
        applied=int(log["applied_output"])
        complete=int(log["completion_output"])
        if not np.array_equal(switched[:committed].view(np.uint32),
                              fixed050[:committed].view(np.uint32)):
            raise RuntimeError(f"Committed PCM differs for {name}")
        both=min(len(switched),len(fixed050))
        diff=np.flatnonzero(np.any(switched[:both].view(np.uint32)!=
                                   fixed050[:both].view(np.uint32),axis=1))
        first=int(diff[0]) if len(diff) else -1
        local=switched[max(0,applied-rate//10):min(len(switched),applied+rate//10)]
        derivative=np.max(np.abs(np.diff(np.asarray(local),axis=0)),axis=1)
        insertedSilence=unexpected_silence(local,rate)
        boundary=float(np.max(np.abs(switched[applied]-switched[applied-1])))
        before=switched[max(0,applied-rate):max(0,applied-rate//5)]
        after=switched[min(len(switched),complete+rate//5):
                       min(len(switched),complete+rate)]
        corrBefore,sideBefore=properties(before)
        corrAfter,sideAfter=properties(after)
        specBefore=spectrum_metrics(before,rate)
        specAfter=spectrum_metrics(after,rate)
        ipdBefore,ildBefore=stereo_spectral_metrics(before)
        ipdAfter,ildAfter=stereo_spectral_metrics(after)
        finite=bool(np.isfinite(switched).all())
        peak=float(np.max(np.abs(switched)))
        rmsBefore=float(np.sqrt(np.mean(np.asarray(before,dtype=np.float64)**2)))
        rmsAfter=float(np.sqrt(np.mean(np.asarray(after,dtype=np.float64)**2)))
        frequencyBefore=frequencyAfter=float("nan")
        if name=="sine":
            frequencyBefore=sine_frequency(before,rate)
            frequencyAfter=sine_frequency(after,rate)
        rows.append((name,len(switched),committed,applied,complete,first,
                     first-committed if first>=0 else -1,finite,peak,insertedSilence,boundary,
                     float(np.percentile(derivative,99)),float(np.max(derivative)),
                     rmsBefore,rmsAfter,corrBefore,corrAfter,sideBefore,sideAfter,
                     ipdBefore,ipdAfter,ildBefore,ildAfter,
                     *specBefore,*specAfter,frequencyBefore,frequencyAfter,
                     float(log["dsp_seconds"]),int(log["peak_rss_kib"])))
        resolutionStages,fir=stage_comparison(target/"diagnostics",name)
        for resolution,count,firstStage in resolutionStages:
            stages.append((name,resolution,count,*
                           (firstStage[f] if firstStage[f] is not None else -1
                            for f in ("fft","phase","ifft","ola"))))
        firStages.append((name,fir[0],fir[1]["low_fir"],fir[1]["high_fir"],
                          fir[1]["output_fir"]))
        print(name,"prefix",committed,"first_diff",first,
              "sine_hz",frequencyAfter,"finite",finite,flush=True)
    with (target/"audio_metrics.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("source","output_frames","committed_output","applied_output",
                         "completion_output","first_difference","unaffected_margin_frames",
                         "finite","peak","unexpected_silence_windows","boundary_derivative","local_derivative_p99",
                         "local_derivative_max","rms_before","rms_after",
                         "lr_corr_before","lr_corr_after","side_mid_before","side_mid_after",
                         "ipd_rms_before_rad","ipd_rms_after_rad",
                         "ild_rms_before_db","ild_rms_after_db",
                         "spectral_delta_median_before","spectral_delta_p90_before",
                         "spectral_delta_median_after","spectral_delta_p90_after",
                         "sine_hz_before","sine_hz_after","dsp_seconds","peak_rss_kib"))
        writer.writerows(rows)
    with (target/"stage_comparison.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("source","resolution","common_frames","first_fft_mismatch",
                         "first_phase_mismatch","first_ifft_mismatch","first_ola_mismatch"))
        writer.writerows(stages)
    with (target/"fir_comparison.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("source","common_output_probes","first_low_fir_mismatch",
                         "first_high_fir_mismatch","first_output_fir_mismatch"))
        writer.writerows(firStages)
    clickRows=[]
    for label,path in (("A050",target/"baseline/click_050.wav"),
                       ("B075",target/"baseline/click_075.wav"),
                       ("Cswitch",target/"raw/click_switch.wav")):
        for number,(position,peak,width) in enumerate(click_attacks(details(path),48000),1):
            clickRows.append((label,number,position,position/48000,peak,width))
    nearRows=[]
    for name in ("click","drums"):
        info=dict(line.split("=",1) for line in
                  (target/"diagnostics"/f"{name}_switch_on.txt").read_text().splitlines()
                  if "=" in line)
        changed=details(target/"raw"/f"{name}_switch_on.wav")
        fixed=details(target/"baseline/click_050.wav" if name=="click"
                      else raw/"drums_050.wav")
        committed=int(info["committed_output"])
        if not np.array_equal(changed[:committed].view(np.uint32),
                              fixed[:committed].view(np.uint32)):
            raise RuntimeError(f"Near-attack committed prefix changed: {name}")
        applied=int(info["applied_output"])
        derivative=float(np.max(np.abs(changed[applied]-changed[applied-1])))
        finite=bool(np.isfinite(changed).all())
        attacks=click_attacks(changed,48000) if name=="click" else []
        changedAttack=local_attack(changed,committed,48000)
        fixedAttack=local_attack(fixed,committed,48000)
        nearRows.append((name,int(info["request_input"]),committed,applied,
                         int(info["completion_output"]),derivative,finite,
                         len(attacks),max((attack[2] for attack in attacks),default=-1),
                         *changedAttack,*fixedAttack))
        if name=="click":
            for number,(position,peak,width) in enumerate(attacks,1):
                clickRows.append(("Cswitch_on",number,position,position/48000,peak,width))
    with (target/"near_attack.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("source","request_input","committed_output","applied_output",
                         "completion_output","boundary_derivative","finite",
                         "detected_clicks","max_half_peak_width_samples",
                         "switch_attack_position","switch_attack_peak","switch_attack_width",
                         "golden_attack_position","golden_attack_peak","golden_attack_width"))
        writer.writerows(nearRows)
    with (target/"click_attacks.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("mode","attack_number","output_sample","output_seconds",
                         "peak","half_peak_width_samples"))
        writer.writerows(clickRows)


if __name__=="__main__":
    main()
