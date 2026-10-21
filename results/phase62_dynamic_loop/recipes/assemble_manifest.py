"""旧集計入口。新しい監査計画と新規出力先を必須にする。
過去のMANIFESTは変更しない。旧rowsだけのPASS・固定期待数の実施数転記を廃止。
元レシピは c4bdbb44:results/phase62_dynamic_loop/recipes/assemble_manifest.py で復元可。
"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[3]/'scripts/phase62_aggregation_manifest.py'),run_name='__main__')
