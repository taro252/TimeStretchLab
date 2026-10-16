"""Keep the Phase35 comparison failures; independently audit baseline live replay."""
import json,subprocess
from pathlib import Path
from phase57_study import ROOT,sha
from phase59_native_validation import compare_pcm

def main():
    reference=ROOT/'build/phase59_frozen/captured_reference';raw=ROOT/'build/phase59_frozen/reference_scope_work.f32';rows=[]
    for name in ('native_smoke_v2','native_smoke_v3'):
        root=ROOT/'results/phase59'/name
        for i,row in enumerate(json.loads((root/'rows.json').read_text())):
            folder=root/f'case_{i:03d}';actual=folder/'failure_capture.f32'
            if not actual.exists():actual=root/'working/capture.f32'
            prefix=folder/'baseline_live_scope_audit'
            if prefix.with_suffix('.json').exists():raise RuntimeError('Fresh audit required')
            command=[str(reference),row['input'],str(row['initial']),row['preset'],str(folder/'native'),str(raw),str(prefix)]
            p=subprocess.run(command,capture_output=True,text=True,timeout=1800);prefix.with_suffix('.log').write_text(p.stdout+p.stderr)
            record=dict(source_session=str(folder),original_native_pass=row.get('native',{}).get('PASS',False),reference_exit=p.returncode,reference_sha256=sha(reference),original_preplanned_comparison_preserved=True)
            if p.returncode==0:
                info=json.loads(prefix.with_suffix('.json').read_text());record['reference']=info
                record['pcm']=compare_pcm(actual,raw,0,raw.stat().st_size,info['channels'],True,folder)
                record['map_exact']=(folder/'native/dynamic_map.nodes.bin').read_bytes()==prefix.with_suffix('.nodes.bin').read_bytes()
            rows.append(record)
    result=dict(scope='全曲解析＋同一Frontierの旧Phase39/36動的経路。旧Phase35の先行全計画方式の失敗記録を変更しない。',
        rows=rows,all_canonical_pcm_exact=all(r.get('pcm',{}).get('PASS') and r.get('map_exact') for r in rows),
        original_clock_failure_resolved=False)
    (ROOT/'results/phase59/native_reference_scope_audit.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print('canonical live PCM',sum(r.get('pcm',{}).get('PASS',False) for r in rows),'/',len(rows),'original clock FAIL preserved')
if __name__=='__main__':main()
