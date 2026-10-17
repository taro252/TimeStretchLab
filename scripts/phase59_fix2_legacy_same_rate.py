"""SourceNode比較と同じ48kHz/Float32/stereo形式でも製品3版を比較する。"""
import json
import subprocess
import sys
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_native_validation import wav_info
from phase55_study import write_wav


def main():
    data=ROOT/'build/phase59_fix2_artifacts/legacy_same_rate_input';data.mkdir()
    original=ROOT/'results/phase59/native_smoke_v2/inputs/boundary_float_stereo_48000.wav'
    meta=wav_info(original);assert (meta['rate'],meta['channels'],meta['encoding'],meta['bits'])==(48000,2,3,32)
    with original.open('rb') as f:f.seek(meta['data_offset']);pcm=f.read(meta['data_bytes'])
    length=12*48000*2*4
    source=data/'boundary_repeated_12s_float_stereo_48000.wav'
    write_wav(source,48000,2,3,(pcm*((length+len(pcm)-1)//len(pcm)))[:length])
    previous=json.loads((OUT/'legacy_final/manifest.json').read_text());probe=previous['binaries']['probe']['path']
    command=[sys.executable,'-B','scripts/phase59_fix2_legacy.py','--tag','same_rate','--probe',probe,'--input',str(source)]
    manifest=dict(original=str(original),original_sha256=sha(original),generated=str(source),generated_sha256=sha(source),
                  metadata=wav_info(source),recipe='元のFloat32 PCM生バイトを反復して12秒で切る。再サンプル・量子化なし。smokeの6秒Seekと操作列を保つため長さだけ確保。',
                  command=command,scope='正式な既存44.1kHz製品12比較に追加。A/B/C/D/Eと同じSourceNode形式を持つFの比較。装置・source形式と操作列は統一し、素材長の差は明記。')
    with (OUT/'LEGACY_SAME_RATE_INPUT.json').open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2);f.write('\n')
    return subprocess.run(command,cwd=ROOT).returncode


if __name__=='__main__':raise SystemExit(main())
