"""原本を変更せず、Mach nsを共通軸にした図の入力を生成する。"""
import csv
import json
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase58_fix_trace_analyze import table,number


def points(rows,anchor,key,value):
    return [dict(id=i,x=(int(r[key])-anchor)/1e6,y=float(r[value])) for i,r in enumerate(rows)]


def ticks(rows,anchor,output=False):
    return [dict(id=i,x=(int(r['host_ns'] if output else r['start_ns'])-anchor)/1e6,
                 label='' if output else r['sequence'],kind='HAL時刻' if output else '実際の入口') for i,r in enumerate(rows)]


def lane(label,kind,maxy=1,spans=None,tick=None,point=None):
    return dict(label=label,kind=kind,maxY=maxy,spans=spans or [],ticks=tick or [],points=point or [])


def main():
    destination=ROOT/'build/phase59_fix2_artifacts/timeline_data';destination.mkdir(exist_ok=True)
    figures=[];inputs=[]
    native=ROOT/'build/phase59_fix_artifacts/device_final/dynamic_normal/case_000/native'
    summary=json.loads((native/'summary.json').read_text());callbacks=list(csv.DictReader((native/'callbacks.csv').open()))[:7]
    anchor=int(callbacks[0]['start_ns']);worker=list(csv.DictReader((native/'worker.csv').open()));spans=[]
    for r in worker:
        begin=summary['clock_mach_ns']+(float(r['start_s'])-summary['clock_pipeline_s'])*1e9
        end=begin+float(r['wall_s'])*1e9
        if end>anchor-5e6 and begin<anchor+65e6:
            spans.append(dict(id=len(spans),x0=(begin-anchor)/1e6,x1=(end-anchor)/1e6,state='合成advance'))
    figures.append(dict(name='startup_software',title='初回の時計異常：ソフトウェア記録',
        subtitle='sampleTime 0 → 1160（要求512、余分648）。最初の2回と合成advanceは重ならない。',xmin=-5,xmax=65,markers=[],
        note='0ms＝最初のcallback入口。OS状態と物理出力は未観測。記録された合成区間とFIFOの整合だけを示す。',
        lanes=[lane('OS状態','spans'),lane('要求の時刻','ticks',tick=ticks(callbacks,anchor)+[dict(r,id=r['id']+100) for r in ticks(callbacks,anchor,True)]),
               lane('FIFO\n0〜16384','line',16384,point=points(callbacks,anchor,'start_ns','fifo_before')),lane('合成の実行区間','spans',spans=spans)]))
    inputs += [native/'summary.json',native/'callbacks.csv',native/'worker.csv']
    legacy=ROOT/'build/phase59_fix2_artifacts/legacy_investigation/2_probe_smoke_candidate'
    callbacks=list(csv.DictReader((legacy/'callbacks_0.csv').open()));first=next(r for r in callbacks if int(r['wanted'])>int(r['received']));anchor=int(first['start_ns'])
    selected=[r for r in callbacks if anchor-220e6<=int(r['start_ns'])<=anchor+100e6]
    workers=list(csv.DictReader((legacy/'retired_worker_3.csv').open()));spans=[]
    for r in workers:
        begin=int(r['start_mach_ns']);end=int(r['published_mach_ns'])
        if end>anchor-220e6 and begin<anchor+100e6 and end>begin:
            spans.append(dict(id=len(spans),x0=(begin-anchor)/1e6,x1=(end-anchor)/1e6,state='公開間隔'))
    markers=[dict(id=i,x=(int(r['pcm_ready_mach_ns'])-anchor)/1e6,label='公開入口') for i,r in enumerate(workers) if anchor-220e6<=int(r['pcm_ready_mach_ns'])<=anchor+100e6]
    figures.append(dict(name='legacy_fifo_software',title='現行診断版：FIFO不足2482フレーム',
        subtitle='通常の消費が続く中で、公開入口へ到達する前にFIFOが尽きた。生成済みかは、この記録だけでは未確定。',xmin=-220,xmax=100,markers=markers,
        note='0ms＝最初の不足callback。公開入口の前には入力確認とSeek suffix再構成がある。灰色のOS状態は未観測。',
        lanes=[lane('OS状態','spans'),lane('要求の時刻','ticks',tick=ticks(selected,anchor)),
               lane('FIFO\n0〜16384','line',16384,point=points(selected,anchor,'start_ns','fifo')),
               lane('公開から次の公開','spans',spans=spans)]))
    inputs += [legacy/'callbacks_0.csv',legacy/'retired_worker_3.csv']
    old=ROOT/'build/phase59_fix_artifacts/final_long_trace'
    raw=json.loads((old/'post_trace_clock_vm_evidence.json').read_text());rows=raw['callbacks'];anchor=int(raw['clock_jumps'][0]['previous']['start_ns']);epoch=raw['trace_epoch_ns']
    client=[]
    names={'Running':'実行中','Runnable':'実行待ち','Blocked':'待機','Unknown':'未観測'}
    for r in raw['client_states']:
        begin=epoch+number(r,'start');end=begin+number(r,'duration')
        client.append(dict(id=len(client),x0=(begin-anchor)/1e6,x1=(end-anchor)/1e6,state=names.get(r['state']['fmt'],'未観測')))
    ns=ROOT/'build/phase59_fix_artifacts/final_long_trace_native';s=json.loads((ns/'summary.json').read_text())
    dsp=[]
    for r in table(old/'xml/thread-state.xml',{s['dsp_thread']}):
        begin=epoch+number(r,'start');end=begin+number(r,'duration')
        if end>anchor-25e6 and begin<anchor+30e6:dsp.append(dict(id=len(dsp),x0=(begin-anchor)/1e6,x1=(end-anchor)/1e6,state=names.get(r['state']['fmt'],'未観測')))
    marks=[dict(id=i,x=(epoch+number(r,'timestamp')-anchor)/1e6,label='OS過負荷') for i,r in enumerate(raw['hal_events']) if 'Overload' in str(r.get('description',{}).get('fmt'))]
    figures.append(dict(name='midplay_os',title='約85.821秒：Client Overloadと時刻進行異常',
        subtitle='遅い入口の後、次のsampleTimeが余分518フレーム進む。待機理由・計測器との全因果は未確定。',xmin=-25,xmax=30,markers=marks,
        note='0ms＝callback8016入口。赤はOS Client Overload。Native HAL window 0とは別。FIFO不足0・PCM一致でも物理出力は未検証。',
        lanes=[lane('client OS状態','spans',spans=client),lane('要求の時刻','ticks',tick=ticks(rows,anchor)+[dict(r,id=r['id']+100) for r in ticks(rows,anchor,True)]),
               lane('DSP OS状態','spans',spans=dsp),lane('FIFO\n0〜16384','line',16384,point=points(rows,anchor,'start_ns','fifo_before'))]))
    inputs += [old/'post_trace_clock_vm_evidence.json',old/'xml/thread-state.xml',ns/'summary.json']
    path=destination/'figures.json';path.write_text(json.dumps(figures,ensure_ascii=False,indent=2)+'\n')
    manifest=dict(data=str(path),data_sha256=sha(path),inputs=[dict(path=str(p),sha256=sha(p)) for p in inputs],
                  scope='全図の時刻はMach absolute nsを基準点からmsへ変換。欠測を正常に補わず、公開入口を真の生成完了と呼ばない。')
    (OUT/'TIMELINE_DATA.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(path)


if __name__=='__main__':main()
