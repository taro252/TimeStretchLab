"""最終manifestを小さいGit側REPORTへ転記。原本はbuild下へ保持する。"""
import argparse,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);a=p.parse_args();base=a.base.resolve();snap=a.snapshot.resolve();out=ROOT/'results/phase62_control_ab';m=json.loads((snap/'manifest.json').read_text());assert m['source_inventory_sha256']==json.loads((base/'candidate_build_09/BUILD.json').read_text())['source'];assert not (out/'REPORT.md').exists()
for src,name in [(snap/'manifest.json','manifest.json'),(snap/'SOURCE.json','SOURCE.json'),(base/'QUALITY_REUSE_AUDIT_09.json','QUALITY_AUDIT.json'),(base/'REFERENCE_AUDIT.json','REFERENCE_AUDIT.json'),(base/'ENVIRONMENT.json','ENVIRONMENT.json')]:shutil.copy2(src,out/name)
def read(path):return json.loads(path.read_text())
cpu=read(base/'CPU_COMPARISON_v4.json');quality=base/'ab_quality_06';warm={n:read(quality/n/'SUMMARY.json') for n in ['before_warm_serial','after_warm_serial','before_warm_replace','after_warm_replace']};cold={}
for side,folder in [('before',base/'ab_quality_02/before_cold_A270'),('after',quality/'after_cold_A270')]:cold[side]=[json.loads(x) for x in (folder/'measurements.jsonl').read_text().splitlines()]
rows='\n'.join('| '+r['id']+' | '+f"{r['baseline_cpu_percent']:.3f}% | {r['candidate_cpu_percent']:.3f}%"+' |' for r in cpu['rows']);b=m['builds'];fb=b['candidate_build_09'];bs=b['baseline_build_01'];ba=b['baseline_ab_build_03'];fresh=cold['after'][0];raw=m['inputs'];refs=read(quality/'REFERENCES.json')
text=f'''# Phase62 制御負荷・AB入口 結果

判定：機能正確性・native CPU・warm ReturnToA接続は今回実施範囲でPASS。保存点のないfresh初回高速化はINCOMPLETE、今回全体の完了GOにはしない。一般公開・Merodoa既定採用はNO-GOのまま。

## 対象・識別

- 開始HEAD/基準：`{m['baseline_commit']}`、開始main/clean。独立checkoutの作業ブランチ`{m['branch']}`。最新修正を戻していない。
- 最終code/test/script inventory：`{m['source_inventory_sha256']}`（全一覧はSOURCE.json）。CMake/src/testsの未コミット差分SHA：`{m['code_diff']['sha256']}`、{m['code_diff']['bytes']:,} bytes。原本CODE_DIFF.patchはbuild下。基準SHAだけで未コミット版を特定していない。
- CPU変更前：ff＋共通の任意カウンター/同host、inventory `{bs['source']}`。CPU変更後/最終：build09、inventory `{fb['source']}`。
- AB変更前：ff＋同カウンター/同warm host、inventory `{ba['source']}`。baseline_instrumentation.patch＋baseline_ab_additions.patchから再構成可能。最適化をbaselineへ混ぜていない。
- CPU binary before `{bs['binaries']['phase62_control_cpu_native']['sha256']}` / after `{fb['binaries']['phase62_control_cpu_native']['sha256']}`。
- AB binary before `{ba['binaries']['phase62_warm_reenable_native']['sha256']}` / after `{fb['binaries']['phase62_warm_reenable_native']['sha256']}`。
- Apple M1 / MacBookAir10,1 / 16GiB / macOS26.6.2、Apple clang21.0.0、CMake4.3.3。実行体arm64、Release中心。起動shellのunameはx86_64だったが子binaryのarchitecture gateでarm64を別確認。装置は内蔵スピーカー48kHz/512。部分混合のみ64frameへ変更し全6件で512へ復元。物理loopback・試聴承認は実施していない。
- Merodoa本体/依存内/submodule/UI/gitlink/承認SHAは未変更。ステージ・commit・push・履歴書換えは今回行わない。

## 実装

Phase58RealtimePipeline/ProgressiveMacPlaybackEngine/LoopSpeedLedgerへ制御負荷削減を集約した。同期対象なしで早期return、未終端索引と個別進捗/最大3行の要約を使用し、全履歴本体・個別/履歴/終了監査を保持する。待機seekは通知待ち。EOS後の速い速度制御と同leaseの入力identity検証を分け、通常側10ms共有検証＋新epoch force検証とした。既存3秒以内の異常検出受入は維持し、250msへ緩めていない。製品callbackへ処理/通知/確保/ロック/I/Oを追加していない。最初のA時刻の時計読取は検証hostの有限事前確保観測だけである。

Clear Started/Doneを先に確定して外部速度IDを保護し、実採用前Cancelledへの早期確定を修正した。Stop/close中断では開始/PCMの事実を保持して取消/実完了を区別する。未採用Clearは既存requestLoopRange(ReturnToA)で安全に置換でき、専用cancelClear APIは増設しない。Applying/Committed/FixedBoundaryCommittedとKeepPosition退役窓は理由付き拒否。

通常seekの既存完全固定P<=OAを初回Loopへ流用し、全Map/最終長/入力・解析/Preset/速度/resident identityを厳密に検査する。Clearは同速度のA保存点からB/Cまで実際にExact再合成し、B越えPCMをA状態へ継ぎ足さない。P=0も復元済みとして扱う。最終レビューで同速度3連RangeがCP1→CP2→上限失敗する参照寿命漏れも再現し、反復入口とclone後の不要共有だけを通常側で解放した。

最大2実行owner/2checkpoint、FIFO16,384、RAW/program96,000、1GiB予約/既存24MiB共有枠を維持。追加未終端索引8,192 bytesを計上し、未使用B越えPCM領域16,384 bytesを除去。DSP数式・Preset・ゲイン0.5・速度100%の実DSP・Exact/FastLocalの選択は変更していない。

新prepareでは旧全履歴と軽量要約を同時に初期化し、Accepted/PreparingとPipeline生成前Failedへ前回の速度/pending/lastResultが残る問題を修正した。普通の75%適用→Stopから両状態を実測し、修正前の2失敗も保持した。任意カウンターはEngine/InputLease/epochで累積範囲が違うため、同じ範囲内の窓差分だけを用いる。

## 同条件CPU・遅延

CPUは同一240秒stereo PCM16、Candidate100%、通常取得5Hz、native processのみ。30秒×3中央値：{cpu['baseline_median_cpu_percent']:.5f}%→{cpu['candidate_median_cpu_percent']:.5f}%（相対{cpu['relative_reduction_percent']:.2f}%減）。変更後実行前に固定した5%改善基準をPASS。UI/Swift/JSONやアプリ全体の約30–40%とは別指標。n=3の直列観測で統計的因果を主張しない。

| 窓 | baseline CPU | candidate CPU |
|---|---:|---:|
{rows}

寄与別5秒試行では、空履歴のbaselineコピー量は実際に0 bytesでありCPU40%の説明にしていない。全履歴取得は約368回/秒→0、待機seek反復起床→0、入力検証は約162回/秒→約{cpu['attribution'][0]['inclusive_costs']['input_validation']['candidate']['calls_per_s']:.1f}回/秒。monitor等の内側CPU/wallは包含値なので合算しない。窓端RSS最大はbaseline {max(x['baseline_rss_bytes'] for x in cpu['rows'])/1048576:.2f}MiB、candidate {max(x['candidate_rss_bytes'] for x in cpu['rows'])/1048576:.2f}MiB（真のpeak RSSではない）。当該観測の供給/worker確保/期限増分0、callback確保0。広いRT承認とは区別する。

| 遅延（同条件host、A=30/B=32、各1試行） | baseline | candidate |
|---|---:|---:|
| ON意思→送信：旧Clear完了待ち接続 | {warm['before_warm_serial']['on_intent_to_send_s']:.6f}s | {warm['after_warm_serial']['on_intent_to_send_s']:.6f}s |
| ON意思→最初のA PCM：旧直列接続 | {warm['before_warm_serial']['on_intent_to_first_A_PCM_s']:.6f}s | {warm['after_warm_serial']['on_intent_to_first_A_PCM_s']:.6f}s |
| ON意思→最初のA PCM：直接最新Range要求 | {warm['before_warm_replace']['on_intent_to_first_A_PCM_s']:.6f}s | {warm['after_warm_replace']['on_intent_to_first_A_PCM_s']:.6f}s |

直接要求入口はbaselineにも存在する。今回の成果は採用/取消契約・終端ID・資源寿命を修正してその接続範囲を明確にしたことと、Clearの前置Exact削減。Merodoaは今回未接続なのでVM待ちが実アプリで除去されたとは報告しない。Started等の必要待機は残す。

fresh A270の受付→Readyは {cold['before'][0]['accepted_to_ready_s']:.6f}s→{fresh['accepted_to_ready_s']:.6f}sで改善未達。変更後の前置破棄{fresh['cold_discarded_frames']:,}f、前置DSP CPU {fresh['cold_prefix_cpu_s']:.6f}s、解析待ち{fresh['analysis_wait_s']:.9f}s、Map CPU {fresh['map_cpu_s']:.6f}s。A絶対位置までのDSPが支配し、Cとの距離とは扱わない。同prepare再ONはA保存点P={cold['after'][1]['checkpoint_start']:,}から残{cold['after'][1]['cold_discarded_frames']}fだけ再生成し、Ready {cold['after'][1]['accepted_to_ready_s']:.6f}s。先行準備APIは導入せずfresh高速化を完了扱いしない。

## 最終検証台帳

| 集合 | 予定/実施 | 結果・範囲 |
|---|---:|---|
| CPU plain＋寄与試行 | 2program/10窓 | PASS、固定閾値・同条件を再監査 |
| 4連Range・新prepare速度要約の初期化 | 2program/38 checks | PASS、退役後CP1、peak2、owner2、PCM/静止/終了監査 |
| 制御要約・入力監視・Clear再ON競合 | 24program/280 checks | PASS、全39fields・全Accepted・末尾監査 |
| A1/A2/F01/旧Paused Clear代表 | 28program/147 checks | PASS、新binary |
| worker取消・通常Paused制御・動的Clear | 12program/92 checks | PASS、独立Clear RAW/混合含む |
| 実部分混合の置換/Clear/Stop | 6program/6 cases | PASS、64frame実機・callback gateなし・装置復元 |
| AB/cold/warm/prefix独立固定品質 | 12program/88 checks | PASS、変更前cold3再利用＋変更後を含む9新実行 |
| 動的planner/DSP/Map/適用座標 | 20 cases（10遷移×2Preset） | PASS、実測Frontierから独立再計算。suite管理5件PASS・別範囲5件NOT_RUNを保持 |
| 決定的ゲート | Release20＋Debug20、6stage | PASS、最終source |
| 比較基準sourceのパッチ再構成 | 2/2 | PASS、ff＋計測用差分のSHA一致。新たな音声実行なし |
| 凍結参照のsource/library/binary監査 | 10/10 | PASS、今回の新監査。PCM件数へ加算しない |
| 品質再利用・独立窓・実行体整合監査 | 22/22 | PASS、全artifact現SHA照合、PCM再計算は上記品質集合 |
| fresh無保存点の初回高速化 | A0/30/270を測定 | INCOMPLETE、A270約28秒 |
| 新全161/Exact896/Golden25全行列 | NOT_RUN | DSP数式未変更。影響箇所の上記代表回帰を実施 |
| 物理loopback/主観音質/新Merodoa実アプリ/TCC/既定化 | NOT_RUN | 単体/Mock/compile成功で補わない |

正常集合のunexpected missing/padding/rejected=0、callback C++new/malloc/free=0、NaN/Inf=0、owner/checkpoint上限2を確認。独立固定RAWは凍結Phase61 reference SHA `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。動的はbb22由来captured reference SHA `1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`。旧523 source/driver/library/binaryと入力の現SHAを再監査し、製品から参照を作り直していない。各binary/入力/参照/command/期待ID/exit/timeout/完了/結果はmanifestのEXPECTED/SUMMARYと原本を結合する。

CPU用240秒入力SHA `{raw['artificial_240s.wav']['sha256']}`、AB長尺300秒 `{raw['artificial_300s.wav']['sha256']}`。Merodoa人工素材と同一SHA。12秒stereoと6秒mono、44.1kHz stereo Float32既存素材の各SHAもmanifest/実行EXPECTEDへ保存。単純素材を必須参照の代用品としていない。

## 失敗保存・再現・引継ぎ

- clear_repro_02：旧版Started Clearの実PCM速度IDがCompleted前Cancelledとなる実再現。修正後10checksおよび全競合集合をPASS。
- repeat_range_repro_01：旧版4回同速度Range hostの3回目でCP上限FAIL。最終38checksで修正確認。
- summary_reset_repro_01：旧版は75%→Stop→新100%準備中/生成前Failedの両方で75%と旧lastResultが残る。最終版は両Presetで旧履歴を消去する。
- ab_quality_01：OA=0へP>0を要求した旧validator条件不備。専用hit診断＋P=0/破棄0へ修正。ab_quality_02：prefix 16/16成功でもID宣言順で集計拒否。重複なし完全集合照合へ修正。旧SUMMARYを保持。
- ab_quality_05：参照ディレクトリ引数の指定不備で音声実行前停止、0program/0checksのINCOMPLETEを保存。06で正しい引数によって実施し、CPU成功分はソース/実行体照合のうえ再実行していない。
- 初期summary試験の既定速度500000/1000000仮定、旧idle dispatch gateを待つfixture不備も保存し、製品のCPU/音質結果へ転記していない。timeout・build失敗・統計欠落をPASSにしていない。

原本：`{base}`。大容量WAV/RAW/trace/binaryは全てGit管理外。Git側はSOURCE/manifest/REPORT/監査/生成・実行レシピだけ。[設計](../../docs/PHASE62_CONTROL_AB_PERFORMANCE.md)、[検証手順](../../docs/PHASE62_CONTROL_AB_VALIDATION.md)、[Merodoa接続条件](../../docs/PHASE62_MERODOA_HANDOFF.md)を参照。容量境界は50,000,000 bytes、既存証拠を削除していない。

Merodoa側は最新ON意図とfresh inputGeneration/session/renderEpochでrequestLoopRange(ReturnToA)を直列送信し、旧clearPending=falseを必須待ちにしない。新Loop IDの初期位置・明示Resume/取消・全速度ID終端・owner2/CP2・最初のA PCMを受入条件にする。同SHAのheader/archiveで再ビルドして実アプリを再測定する。FastLocal長尺既存失敗、stereo Ready目標、開始時時計、Debug既存期限、主観音質、物理loopback、実TCC・公開承認は閉じない。allowExperimentalLoops=false/publicLoopApproved=false/Capabilities.seek=false/currentCycleSpeedChanges=falseを保持する。
'''
(out/'REPORT.md').write_text(text);print('report',identity(out/'REPORT.md'))
