"""Sequential native boundary/race/resource regressions; no concurrent players."""
import argparse,hashlib,json,platform,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);build=a.build.resolve();fixtures=a.fixtures.resolve();commands=[]
    names=['paused_speed_boundary_tests','paused_speed_loop_tests','phase60_adapter_tests','phase60_lifecycle_tests','phase62_native_tests']
    (out/'provenance.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip(),'dirty_source':True,'engine_source_sha256':sha(ROOT/'src/platform/macos/ProgressiveMacPlaybackEngine.mm'),'pipeline_source_sha256':sha(ROOT/'src/prototype/Phase58RealtimePipeline.cpp'),'binaries_sha256':{n:sha(build/n) for n in names},'driver_sha256':sha(Path(__file__).resolve()),'host':platform.platform()},indent=2)+'\n')
    def run(label,cmd):
        cmd=list(map(str,cmd));start=time.monotonic()
        with (out/(label+'.log')).open('x') as log:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        commands.append({'label':label,'command':cmd,'exit':r.returncode,'wall_s':time.monotonic()-start});(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if r.returncode:raise RuntimeError(label+f' exit {r.returncode}')
    for rate,ch,preset in [(48000,2,'candidate'),(48000,2,'baseline'),(44100,1,'candidate'),(44100,1,'baseline')]:
        name=f'{rate}_{ch}_{preset}';input=fixtures/f'{rate}_{ch}.wav';refs=fixtures/(name+'_refs')
        run(name+'_boundary',[build/'paused_speed_boundary_tests',input,refs,preset])
        run(name+'_stages',[build/'paused_speed_boundary_tests',input,refs,preset,'stages'])
        run(name+'_resources',[build/'paused_speed_boundary_tests',input,refs,preset,'resources'])
        run(name+'_loop',[build/'paused_speed_loop_tests',input,preset])
    run('phase60_adapter',[build/'phase60_adapter_tests',ROOT/'results/phase31/input/mix.wav'])
    run('phase60_lifecycle',[build/'phase60_lifecycle_tests',ROOT/'results/phase31/input/mix.wav'])
    for preset in ['candidate','baseline']:run('phase62_'+preset,[build/'phase62_native_tests',fixtures/'48000_2.wav',out/('phase62_'+preset),'.5','2','10',preset,'controls'])
    (out/'summary.json').write_text(json.dumps({'PASS':True,'commands':len(commands),'boundary_pcm_cases':156,'live_transition_stages':12,'resource_groups':4,'loop_groups':4,'phase60_groups':2,'phase62_native_groups':2},indent=2)+'\n')
    print('PASS native controls',len(commands),flush=True)
if __name__=='__main__':main()
