"""元の描画失敗を残し、同じ実行済み描画関数を専用依存先と新出力先で実行する。"""
import os,json,sys,time,ast,shutil
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';OUT=F/'figure_repair'
sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,identity,source_manifest
names=('waveform_analysis','piano_waveform','boundary_methods')
if len(sys.argv)>1:
 name=sys.argv[1];assert name in names
 import numpy
 original_numpy=numpy.__version__
 sys.path.insert(0,str(F/'plot_dependencies'))
 os.environ['MPLCONFIGDIR']=str(F/'plot_config')
 import matplotlib
 script=F/(name+'.py');tree=ast.parse(script.read_text(),filename=str(script))
 # 上段の定義だけをそのまま実行。既存台帳を生成・再実行する下段は含めない。
 stop=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.If) and ast.unparse(n.test)=='len(sys.argv) > 1')
 tree.body=tree.body[:stop];ns={'__file__':str(script),'__name__':'figure_definition'}
 exec(compile(tree,str(script),'exec'),ns)
 dest=OUT/name;dest.mkdir(parents=True,exist_ok=True)
 if name=='boundary_methods':
  for key in ns['selected']:shutil.copy2(F/name/(key+'.json'),dest/(key+'.json'))
 ns['OUT']=dest
 code=ns['figure']()
 if name=='boundary_methods':shutil.copy2(dest/'boundary_method_comparison.png',dest/'waveform_comparison.png')
 result=json.loads((dest/'FIGURE.json').read_text())
 result.update(original_figure_failure=str(F/name/'figure.log'),driver=identity(script),wrapper=identity(__file__),original_numpy=original_numpy,matplotlib=matplotlib.__version__,notes='Plot only; existing numeric measurements and original failed ledger are unchanged.')
 (dest/'FIGURE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 raise SystemExit(code)
while not (F/'boundary_methods/SUMMARY.json').is_file():time.sleep(5)
assert source_manifest(R)==json.loads((F/'FROZEN_SOURCE.json').read_text())
cases=[dict(id=n,kind='json_pass',required=[n+'/FIGURE.json',n+'/waveform_comparison.png'],result=n+'/FIGURE.json') for n in names]
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),driver=identity(__file__),purpose='Missing matplotlib repair; preserve all original failed plot ledgers'))
for n in names:
 ledger.run(n,[sys.executable,'-B',__file__,n],cwd=R,timeout=180);print(n,ledger.rows[n]['status'],flush=True)
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
