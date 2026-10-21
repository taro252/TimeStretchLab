"""旧v7入口。現在は完全性を必須にする新runnerへ委譲する。
旧実行物と元レシピは c4bdbb44:results/phase62_dynamic_loop/recipes/run_final_gates_v7.py で復元可。
既存final_gates_v7は上書きせず、--outputに新規保存先を指定する。
"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[3]/'scripts/phase62_gate_runner.py'),run_name='__main__')
