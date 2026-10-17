"""Git管理外の実行体・PCM・WAV・ログをSHA manifestへまとめる。"""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    data=ROOT/'build/phase60';manifest=data/'artifact_files.jsonl';count=total=0;large=[]
    excluded={'artifact_files.jsonl','inventory_driver.log','delivery_audit.log','delivery_audit_final.log','report_driver.log','report_final.log','finish_driver.log'}
    with manifest.open('w') as out:
        for p in sorted(data.rglob('*')):
            if not p.is_file() or p.name in excluded or any(x.startswith('audit_') for x in p.relative_to(data).parts):continue
            row={'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)};out.write(json.dumps(row,ensure_ascii=False)+'\n');count+=1;total+=row['bytes']
            if row['bytes']>=50_000_000:large.append(row)
    index={'artifact_root':str(data),'files':count,'bytes':total,'file_manifest':str(manifest),'file_manifest_sha256':sha(manifest),'large_files_not_in_git':large,'excluded_self_referential_logs':sorted(excluded),'recipes':['M4A→拡張WAV: INPUT.jsonのafconvertコマンド。元M4Aはユーザーの保存場所で保持','拡張WAV→対応WAV: INPUT.jsonのrewrap_recipe。data chunk SHAが一致することを確認','承認Phase54: python3 -B scripts/phase60_build_legacy.py','代表Native: python3 -B scripts/phase60_native.py --suite representative --tag <新しいタグ>','指定音源: python3 -B scripts/phase60_native.py --suite user --tag <新しいタグ>','再始動: scripts/phase60_restart_compare.py。既存出力を残し、新しい保存先で実行','参照バイナリの元SHAと生成情報: results/phase59_fix/FROZEN_REFERENCES.json, results/phase58/frozen_product_reference.json, docs/PHASE59_TRANSITION_EXACTNESS.md。別環境での再構築はPCMで再検証'],'restore':'原本はこの絶対artifact_rootに保持。各ファイルのSHAとサイズをJSONLで照合して復元する。別環境では先にユーザーのM4Aと既存固定参照を用意し、記録コマンドを新しい出力先で再実行する。元のFAIL、拡張WAV拒否、訂正前JSON、測定版ソースを上書きしない。','git_policy':'WAV/PCM/実行体/大きな証拠はbuild内で管理。新規blobは50,000,000 bytes未満。履歴変更/LFS移行なし。'}
    (ROOT/'results/phase60/ARTIFACT_INDEX.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');print('artifacts',count,total,'large',len(large))
if __name__=='__main__':main()
