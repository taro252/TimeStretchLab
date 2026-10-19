"""Real-audio CLI control test. Poll UI state, never determine loop B externally."""
import argparse,hashlib,json,queue,re,subprocess,threading,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--host',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    data=a.input.read_bytes();rate=int.from_bytes(data[24:28],'little');commands=[];lines=[];snapshots=[];mail=queue.Queue()
    process=subprocess.Popen([str(a.host.resolve()),str(a.input.resolve()),'2','candidate'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
    def reader():
        for line in process.stdout:lines.append(line);mail.put(line)
    thread=threading.Thread(target=reader,daemon=True);thread.start()
    def send(text):
        process.stdin.write(text+'\n');process.stdin.flush();commands.append(dict(command=text,at_monotonic=time.monotonic()))
    def snapshot():
        send('status');deadline=time.monotonic()+10;state=None
        while time.monotonic()<deadline:
            line=mail.get(timeout=max(.01,deadline-time.monotonic()))
            m=re.search(r'state=(\w+).*session=(\d+).*input=(\S+)',line)
            if m:state=dict(state=m[1],session=int(m[2]),input=m[3])
            m=re.search(r'loop=(\d+) (\w+) cycles=(\d+) clearPending=(\d+) range=\[(\d+),(\d+)\).*requestedSpeed=(\S+) appliedSpeed=(\S+)',line)
            if m and state:
                state.update(id=int(m[1]),loop_state=m[2],cycles=int(m[3]),clear_pending=bool(int(m[4])),a=int(m[5]),b=int(m[6]),requested=float(m[7]),applied=float(m[8]));snapshots.append(state);return state
        raise RuntimeError('status timeout')
    def wait(predicate):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            value=snapshot()
            if value['state']=='Failed':raise RuntimeError('native Failed')
            if predicate(value):return value
            time.sleep(.1)
        raise RuntimeError('state timeout')
    error='';good=False
    try:
        first=wait(lambda s:s['state']=='Playing');send(f'loop 0 {rate*2}')
        armed=wait(lambda s:s['id'] and s['loop_state'] in ('Armed','Active') and s['cycles']>=1)
        send('speed 0.75');send('speed 0.75');wait(lambda s:s['applied']==.75 and s['cycles']>=armed['cycles'])
        send('pause');wait(lambda s:s['state']=='Paused');send(f'loop {rate//4} {3*rate//4}')
        paused=wait(lambda s:s['state']=='Paused' and s['a']==rate//4 and s['b']==3*rate//4 and s['input']==str(rate//4))
        if paused['cycles']!=0:raise RuntimeError('paused loop advanced')
        send('resume');wait(lambda s:s['state']=='Playing' and s['cycles']>=1);send('clear')
        wait(lambda s:s['loop_state']=='Cancelled' and not s['clear_pending']);send('stop');send('play')
        wait(lambda s:s['state']=='Playing' and s['loop_state']=='Disabled' and s['cycles']==0);good=True
    except Exception as exc:error=str(exc)
    finally:
        if process.poll() is None:
            try:send('quit')
            except BrokenPipeError:pass
        try:process.wait(timeout=30)
        except subprocess.TimeoutExpired:process.kill();process.wait();error+=' process timeout';good=False
        thread.join(timeout=5)
    (a.output/'process.log').write_text(''.join(lines));(a.output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    summary=dict(PASS=good and process.returncode==0,exit=process.returncode,error=error,host_sha256=hashlib.sha256(a.host.read_bytes()).hexdigest(),input_sha256=hashlib.sha256(data).hexdigest(),snapshots=snapshots)
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n');print('CLI',summary['PASS'],error);return int(not summary['PASS'])
if __name__=='__main__':raise SystemExit(main())
