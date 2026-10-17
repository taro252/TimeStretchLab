"""全実測を読んでPhase60の実験引き継ぎ判定を作る。過去結果は変更しない。"""
import json,csv,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase60'
def number(v):return f'{v:.6f}' if isinstance(v,(int,float)) else '未測定'
def read(p):return json.loads((OUT/p).read_text())
def main():
    quality=read('QUALITY.json');rep=read('native_representative/summary_reviewed.json');user=read('native_user_canonical/summary.json');restart=read('native_user_restart/summary.json');tests=read('RESULT_TESTS.json');input=read('INPUT.json');extra=read('LIFECYCLE_EXTRA.json')
    current=read('CURRENT_LEGACY.json') if (OUT/'CURRENT_LEGACY.json').exists() else None
    currentRows=[current] if current and current.get('summary') else []
    captures=[r for study in (rep,user) for r in study['rows'] if r.get('summary')]+currentRows
    restartRows=[r for r in restart['rows'] if r.get('summary')]
    sessions=[(r['summary']['engine'],s,r) for r in captures+restartRows for s in r['summary']['sessions']]
    new=[s for engine,s,_ in sessions if engine=='progressive'];old=[s for engine,s,_ in sessions if engine.startswith('legacy')]
    pcm=[r for r in captures if 'pcm' in r]
    balanced=bool(new) and all(not s['workgroup']['active'] and s['workgroup']['joins']==s['workgroup']['leaves']==s['workgroup']['restores'] and not any(s['workgroup'][k] for k in ('policy_errors','join_errors','restore_errors','interval_errors','query_errors','wait_errors','wake_errors')) for s in new)
    api=all(r['exit']==0 for r in rep['rows'] if r['name'] in ('release_adapter_api','debug_adapter_api'))
    newSupply=bool(new) and all(s['missing_frames']==s['underrun_calls']==s['rejected_writes']==0 and s['native']['callback_deadline_misses']==0 and not s['error'] for s in new)
    complete=rep['measurement_completed'] and user['measurement_completed'] and restart['measurement_completed']
    currentReady=bool(current and current.get('summary') and current.get('pcm',{}).get('PASS'))
    handoff=complete and api and balanced and newSupply and quality['PASS'] and tests['PASS'] and extra['PASS'] and rep['pcm_pass'] and user['pcm_pass'] and restart['stop_play_pass'] and currentReady
    audit=read('DELIVERY_AUDIT.json') if (OUT/'DELIVERY_AUDIT.json').exists() else None
    verdict=dict(experimental_handoff='PASS' if handoff else 'PARTIAL',experimental_adapter_implemented=True,public_experimental_api_available=True,legacy_default_preserved=True,experimental_engine_selectable=True,progressive_dynamic_supported=api,all_161_speeds_supported=api,latest_wins_preserved=api,phase59_pcm_contract_preserved=quality['PASS'] and all(r['pcm']['PASS'] for r in pcm),audio_workgroup_integrated=balanced,macos_native_playback_verified=complete and newSupply,pause_resume_verified=api,stop_play_verified=api and restart['stop_play_pass'],eos_verified=api and all(s['eos'] for r in captures if r['summary']['engine']=='progressive' for s in r['summary']['sessions'] if s['trigger']=='eos'),diagnostics_available=True,ab_comparison_tool_available=complete,user_reproduction_wav_tested=False,user_reproduction_underrun_free=False,user_supplied_m4a_decoded_wav_tested=user['measurement_completed'],user_supplied_decoded_progressive_underrun_free=all(s['missing_frames']==s['underrun_calls']==0 for r in user['rows'] if r.get('summary',{} ) and r['summary']['engine']=='progressive' for s in r['summary']['sessions']) and user['measurement_completed'],missing_frames=sum(s['missing_frames'] for s in new),underrun_calls=sum(s['underrun_calls'] for s in new),golden_pass=quality['PASS'],legacy_regression_passed=quality['PASS'] and all(r['pcm']['PASS'] for r in pcm if r['summary']['engine'].startswith('legacy')) and all(s['missing_frames']==s['underrun_calls']==0 for s in old),merodoa_handoff_ready=handoff,gate_2_passed=False,general_release_ready=False,product_integration_ready=False,merodoa_modified=False,physical_audio_continuity_verified=False,git_blob_limit_verified=bool(audit and audit['PASS']))
    verdict['legacy_current_native_passed']=bool(current and current['exit']==0 and current['pcm']['PASS'])
    (OUT/'VERDICT.json').write_text(json.dumps(verdict,ensure_ascii=False,indent=2)+'\n')
    scope={'experimental_handoff':'新API、接続、ライフサイクル、代表PCMと今回の実機に限る。一般公開・Gate2・Sandbox保証ではない。','user_reproduction_wav_tested':'false。当時Merodoaのデコード済みWAV/SHA/装置/操作履歴は未確認。指定M4Aから新規変換した同一WAVのA/Bは別のtrue欄で示す。','missing_frames':'正式代表・指定音源全曲・同音源のprefix再始動を通したProgressive合計。旧版はREPORT別表。','legacy_regression_passed':'既存CTest/Golden、独立生成PCMと今回の供給を対象。過去のFIFO不足を否定しない。','pcm':'Progressive callback受信rawとLegacy公開rawを分ける。条件数はREPORT、通常計測の個別PCM正確性は未測定。','gate_2_passed':'Phase59 Fix2のfalseを維持。OS全区間、初回時計、物理出力を未解決のまま成功扱いしない。','commits':'このPhaseでcommit/Pushなし。GitHEAD診断はビルド元HEAD、変更全体の識別はソース/実行体manifestを併用する。'}
    (OUT/'VERDICT_SCOPE.json').write_text(json.dumps(scope,ensure_ascii=False,indent=2)+'\n')
    lines=['# TimeStretchLab Phase 60 結果','',f'**Experimental Handoff：{verdict["experimental_handoff"]}。Gate 2未合格、一般公開向けは未成立。** この作業ではMerodoa本体・submodule・既定経路を変更していない。コミット・Pushは実施していない。','',
    '## 1. 実装内容','', '`ProgressiveMacPlaybackEngine` と `macos_progressive_playback_engine`、公開能力情報、独立A/Bホストを追加した。既存Phase58/59を所有する薄い接続層であり、DSP・TimeMap・L1/L2・safe-density・位相・OLA・FIRを変更していない。','',
    '## 2. 変更ファイル','', '新規：`src/platform/macos/ProgressiveMacPlaybackEngine.{h,mm}`、`src/playback/ProgressiveContract.h`、比較CLI2本、Objective-C++例、契約/API/結果集計テスト、Phase60実行/監査スクリプト、3文書と結果。既存の変更はCMakeとRealtimePipelineの読み取り専用位置標本だけ。旧MacPlaybackEngine/PlaybackEngine公開API・既定動作は不変。','',
    '## 3. 新エンジンAPI','', 'prepare / play / pause / resume / stop / setSpeed / state / snapshot / position / core/native diagnosticsを公開。シーク能力falseで拒否する。prepareのtrueはAcceptedであり、Ready完了ではない。状態と速度要求のID/世代を区別する。詳細は[設計](../../docs/PHASE60_EXPERIMENTAL_ENGINE.md)。','',
    '## 4. ビルドとリンク','', 'Release/Debug arm64とブリッジ例がビルド成功。アプリは新ターゲットを明示リンクする。承認旧版はSHA `039592e59cc1a525b495e38d3cedeb6c050792b1` を別CMake graphへexportし、全blobを検査して別プロセスで使用した。`LEGACY_BUILD.json`、`FINAL_BUILD_V4.json`、各実機manifestに実行体/ソースSHAを保存。','',
    '## 5. 実時間制御','', f'入力常駐・Audio Workgroup・Mach policy・動的計画を必須指定。Ready後に昇格確認して開始し、Pause/Stop/EOSで静止・離脱・復元する。正式Progressive {len(new)}セッションのjoin/leave/restore対応：{"合格" if balanced else "不合格"}。OS全観測・確保全入口の証明ではない。C++ new/OS faultはnull。','',
    '## 6. 速度変更','', '40〜200%の161値をAPIから受付確認し、Ready中の160件置換と最後の保留、Stop取消、古い世代の拒否を検査した。動的実機では0.40から0.49、0.50、2.00、1.00への計画がCompletedとなり、同時要求0.41/2.00はReplacedとして保存。Candidate/Baseline各々の実Frontier・全Map・全raw PCMが固定旧参照と一致した。Appliedは可聴完了ではない。','',
    '## 7. ライフサイクル','', f'Release/Debugの新API試験が成功：準備中Stop、予算拒否、同時準備拒否、失敗後の新prepare、Pause/Resume、要求中Stop、Stop→Play、EOS→Play、曲/世代分離、模擬route安全停止。正式代表{rep["executions"]}実行/{rep["sessions"]}セッション、同一音源再始動4実行8セッションを別集計。再始動8件はprefix停止であり自然EOSと呼ばない。実装上のStopはコンストラクター内のSHA/複製完了を待つことがある。','',
    '## 8. 音質回帰','', f'固定の独立参照12条件、動的6論理+7増分チャンク、Release/Debug関連CTest各19件が成功。実機PCMは{len(pcm)}条件：Progressive callback受信rawとLegacy公開rawを分け、全Float32生ビット・長さ・順序・SHAを照合した。検証用参照はPhase57以前の固定参照と変更前Phase39/Phase36参照。1140/6216/51344の全研究行列は再実行せず、元結果と参照を保護した。','',
    '## 9. Golden','', '25/25。元WAVのSHAとraw生ビットを確認した。追加の結果集計/RIFF包み直し5試験も成功。ログはQUALITY_DRIVER、RESULT_TESTSを参照。','',
    '## 10. A/B実機試験','', f'指定M4A由来の対応WAV：44.1kHz stereo Float32、{input["frames"]:,}フレーム、{input["duration_s"]:.6f}秒。SHA `{input["wav_sha256"]}`。同じWAV、Candidate、1.00倍、出力装置ID72/48kHz/512でA→B/B→Aを実行した。当時のMerodoa WAVの同一SHA・装置名・操作履歴は未確認。','',
    '|実行|計測|状態|不足frames|不足calls|callback期限|worker期限|host/sample/HAL|PCM|','|---|---|---|---:|---:|---:|---:|---|---|']
    for r in user['rows']+currentRows:
        if not r.get('summary'):continue
        s=r['summary']['sessions'][0];lines.append(f'|{r["name"]}|'+('検証付き' if 'pcm' in r else '通常')+f'|{s["state"]}|{s["missing_frames"]}|{s["underrun_calls"]}|{s["native"]["callback_deadline_misses"]}|{s.get("worker_deadline_misses") if s.get("worker_deadline_misses") is not None else "未測定"}|{s["native"]["host_missing"]+s["native"]["host_backwards"]+s["native"]["host_cadence_errors"]}/{s["native"]["sample_errors"]}/{s["native"]["hal_window_misses"]}|'+('PASS' if r.get('pcm',{}).get('PASS') else '未測定')+'|')
    lines+=['','current_legacy_userは同一checkoutの既存製品経路で、承認039592eの旧版と版を区別する。旧版が今回不足0でも、過去80,765不足を否定しない。再現素材のPCMが当時と完全同一とは主張しない。比較詳細は[実機比較](../../docs/PHASE60_AB_VALIDATION.md)。','',
    '## 11. CPU・メモリ・起動と再始動','', '|実行|最初の要求→PCM秒|プロセスCPU秒|DSPワーカーCPU秒|最大RSSバイト|常駐入力バイト|','|---|---:|---:|---:|---:|---:|']
    for r in user['rows']+currentRows:
        if not r.get('summary'):continue
        s=r['summary']['sessions'][0];lines.append(f'|{r["name"]}|{s["first_pcm_from_request_s"]:.6f}|{s["process_cpu_s"]:.6f}|{number(s.get("worker_cpu_s"))}|{s["peak_rss_bytes"]}|{s.get("resident_input_bytes") if s.get("resident_input_bytes") is not None else "未測定"}|')
    lines+=['','通常計測だけをCPU/RSSの主比較とする。検証付きは旧版のworker SHAと新版の事前確保callback captureという異なる負荷を含む。RSSはプロセスの実メモリ使用量で、ここではプロセス生涯最大値。Coldは新プロセス・解析cacheなしで、事前入力SHAによるOS cacheの温まりを含む。OS cacheをpurgeしていない。','', '|同音源Stop→Play|session|要求→PCM秒|不足frames|','|---|---:|---:|---:|']
    for r in restartRows:
        s=r['summary']['sessions'][1];lines.append(f'|{r["name"]}|{s["session"]}|{s["first_pcm_from_request_s"]:.6f}|{s["missing_frames"]}|')
    lines+=['',f'入力複製/常駐はセッション当たり約{input["wav_bytes"]:,}bytesずつ。自然EOS/Stopで実入力を解放し、診断値は保持する。512MiB/28,800,000フレームの入力上限、予約予算1GiB、同時入力/DSP所有1つを明示した。Phase54解析cacheは共用せず、Stop→Playで再準備する。','',
    '## 12. 実験統合の成立範囲','', f'Experimental Handoff={verdict["experimental_handoff"]}。明示選択、対応WAVの実出力、動的速度、診断、制御・所有権、比較・リンク手順を確認した。統合先の署名済みApp Sandbox、security-scoped URL寿命、実装置差替え、物理出力連続性は後続Merodoa試験。','',
    '## 13. 既存不具合と新規不具合','', 'Phase59 Fix2の初回時計不連続、旧FIFO供給停止、OS欠測、物理loopback未実施は未解決のまま。今回の成功で過去FAILを置き換えない。今回の初回音源変換は拡張WAVとなり4実行が再生前に拒否された。原本・ログを保存し、PCM payloadを保持したRIFF包み直しで解消した。集計コードの空集合all()による成功も修正し、旧JSONを残してsummary_reviewedへ訂正した。音声APIの不足を無音補填で隠す修正はしていない。測定版CLIのanalysis_done_at_readyは入力受領完了を表す旧欄であり、全解析完了とは解釈しない。最終CLIは欄名を訂正し、MEASUREMENT_FIELD_REVIEWとFINAL_HOSTへ範囲を保存した。RTライブラリは全曲測定版と同一SHAで、最終CLIの短尺全PCMも再照合した。追加ターゲット登録直後のMake再読込順序によるビルド停止は明示configureで解消し、失敗ログを保存した。MerodoaのXcodeスキーム・MacLibraryViewには開始後の別差分を検出したが、この作業は操作せず保持した。接続7ファイル・HEAD・submoduleは不変。初回の全SHA監査と、当該UI/スキーム差分を区別した監査訂正をともに保存した。','',
    '## 14. Merodoaへの引き継ぎ可否','', f'開発版の実験接続：{verdict["experimental_handoff"]}。[引き継ぎ](../../docs/PHASE60_MERODOA_HANDOFF.md) にCMakeの追加archive依存、専用直列キュー、Accepted/Ready、状態/速度/位置変換、入力lease、Stop/破棄と明示切戻しを記載した。Merodoa本体とsubmoduleの更新・SwiftUI設定画面は実施していない。固定するPhase60完成コミットは別途レビュー・コミット後に確定する。','',
    '## 15. 今後必要な修正','', 'MerodoaのApp Sandbox実機・同一デコード済みWAVと装置での再現、入力権限/予算、長時間の操作上限対応、シーク能力の別設計、物理連続性と既知時計/OS問題の調査が残る。一般公開向けproduct_integration_readyはfalse。Gitは50,000,000 bytes制限と既存フックを維持し、大容量証拠はbuild/phase60にSHA/復元レシピ付きで保存する。','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    print(verdict['experimental_handoff'],'new missing',verdict['missing_frames'],'PCM',len(pcm))
if __name__=='__main__':main()
