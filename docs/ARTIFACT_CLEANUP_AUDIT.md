# ローカル成果物の初回容量監査

測定日時：2026-10-20 12:51:29 JST。GBは1,000,000,000 bytes。対象は現在のローカル作業ツリー。

実データへのアーカイブ作成・削除・復元は未実施。DSP・再生エンジン・品質基準・既存REPORT/manifestは変更していない。新しく生成した監査JSONだけを検証付きgzipで保管した。

## 容量と分類

| 対象 | 論理容量 GB | ファイル割当量 GB |
| --- | ---: | ---: |
| 作業ツリー（.git除外） | 91.086 | 91.986 |
| results | 60.855 | 61.146 |
| build | 30.224 | 30.830 |

| 分類 | GB | 説明 |
| --- | ---: | --- |
| KEEP・永久保護 | 38.883 | Git追跡、Golden、入力、独立参照、baseline、判定資料・レシピ |
| KEEP・直近保護 | 4.230 | 直近7日の成果物 |
| ARCHIVE | 9.225 | 確認済み生成出力。383単位／383ファイル |
| PRUNE | 0.000 | 30日超・未参照・再生成可能なCMake中間物。この監査では候補なし |
| REVIEW | 38.741 | 未解決/NO-GO、用途不明、参照用途・復元経路未確定 |

同一容量プールでの論理削減見込みは **約0.814 GB**。先頭・中央・末尾の標本をzlibで圧縮した概算で、実際のzstd/gzipサイズは未測定。圧縮だけでは原本を削除しないため空きは増えない。検証済みアーカイブ指定なしの即時削除可能量と、今回の実データ解放実績は **0 GB**。

別の容量プールへ保管して原本を削除する場合、対象の論理量は最大約9.225 GB。APFSの共有ブロックやスナップショット等により、この量がそのまま空く保証はない。監査時空き容量は19.205 GB。割当量も共有ブロックの独占使用量ではない。

## 容量上位のPhase

| Phase | GB | ファイル数 |
| --- | ---: | ---: |
| phase62_fix | 6.514 | 60,025 |
| phase45 | 5.378 | 2,671 |
| phase58_fix | 5.191 | 22,704 |
| phase2 | 5.142 | 105 |
| phase61_fast_seek | 4.476 | 9,951 |
| phase51 | 3.628 | 826 |
| phase59_fix2 | 3.540 | 35,835 |
| phase62 | 2.852 | 9,683 |
| phase36 | 2.640 | 374 |
| phase35 | 2.472 | 578 |
| phase43 | 2.446 | 1,393 |
| phase3 | 2.159 | 77 |
| phase55 | 2.091 | 368 |
| phase52 | 2.059 | 1,193 |
| phase40 | 1.771 | 343 |

## 上位ファイル

| 相対パス | GB |
| --- | ---: |
| `build/phase58_fix_frozen/underrun_flight100.trace/Trace1.run/Attachments/trace-data.atrc` | 0.926 |
| `build/phase58_fix_frozen/ktrace_archives/instrumentsTdATTB.ktrace.gz` | 0.613 |
| `build/phase58_fix_frozen/ktrace_archives/instrumentsMa7U93.ktrace.gz` | 0.581 |
| `results/phase45/traces/drums_actual_3m/states.xml` | 0.325 |
| `results/phase14/benchmark/mix_repeat_900.wav` | 0.318 |
| `build/phase59_fix2_artifacts/trace_legacy_delayed/legacy_os_timeline_reviewed.json` | 0.299 |
| `build/phase61_fast_seek/performance_music/music_300s_400000_baseline_reference.f32` | 0.265 |
| `build/phase61_fast_seek/performance_music/music_300s_400000_candidate_reference.f32` | 0.265 |
| `build/phase59_fix2_artifacts/trace_legacy_delayed/xml/syscall.xml` | 0.256 |
| `results/phase44/traces/mix_10m_state.xml` | 0.240 |

上位50ファイル・ディレクトリ、拡張子別、Git状態別、全候補の理由は `build/artifact_cleanup_audit_20261020/report.txt` と `dry-run.txt` に保存。ディレクトリは親子で容量が重複するため合算しない。

## 圧縮候補の内訳

| Phase | 元サイズ GB | ファイル数 |
| --- | ---: | ---: |
| phase2 | 1.891 | 12 |
| phase3 | 1.891 | 12 |
| phase37 | 1.010 | 136 |
| phase35 | 0.712 | 4 |
| phase36 | 0.712 | 4 |
| phase4 | 0.712 | 4 |
| phase5 | 0.712 | 4 |
| phase7 | 0.631 | 74 |
| phase6 | 0.451 | 16 |
| phase8a | 0.230 | 32 |
| phase31 | 0.108 | 15 |
| phase9c | 0.092 | 32 |
| phase9b | 0.046 | 16 |
| phase9a | 0.014 | 8 |
| phase32 | 0.013 | 14 |

## 保護・保留と参照照合

Phase 12 Goldenと旧比較入力は保管規則と実際のmanifest参照を用いて保護。Phase 47の再解析指定トレース、Phase 57〜62の固定参照、Phase 62/62 FixのNO-GO関連証拠を保持。build全体を削除可能とは扱わない。

Golden/試聴WAVとPhase 57・58・62の固定参照の読み取り照合は38件、全件一致。候補の全383ファイル（9.225 GB）も読み取りでSHA-256を採取した。既存期待値との一致147件、既存期待値なし236件、不一致0件。原本は変更していない。

保存場所を解決できない期待SHA付き参照は3,710記録。旧パス、基点不明、過去アーカイブへの移動、実際の欠損を区別する必要があり、データ消失の断定件数ではない。詳細はsummary.jsonと完全な監査JSONに保存。これらを削除許可の根拠にはしない。

## 検証結果と推奨順序

- 一時リポジトリのArtifactCleanupTests：36テスト成功。WAV/CSV/trace、zstd/gzip、破損、変更・置換、権限・容量不足、排他、リンク、再実行、非ASCIIパス、内部未完了trace等を確認。
- 既存GitBlobSizeGuardTests：5テスト成功。staged容量検査と差分の空白検査も合格。
- 実データの --report / --dry-run：完了、監査エラーなし。実データの圧縮・削除は未実施。
- まず小さいphase9aで保管・別領域復元を確認し、次に候補量の大きいphase2、phase3、phase37へ進む。各PhaseのKEEP/REVIEWは対象外。
- 同一容量プールの圧縮だけでは効果が小さいため、容量確保を優先する場合は非公開の別媒体への保管を検討する。

```sh
python3 scripts/artifact_cleanup.py --dry-run --phase phase2 --details
python3 scripts/artifact_cleanup.py --archive --phase phase2 --confirm
python3 scripts/artifact_cleanup.py --verify --archive-manifest /path/to/archive_manifest.json
python3 scripts/artifact_cleanup.py --restore --archive-manifest /path/to/archive_manifest.json --restore-dir /path/to/empty-restore-check --confirm
python3 scripts/artifact_cleanup.py --prune --archive-manifest /path/to/archive_manifest.json --confirm
```

上の変更コマンドはユーザーが選択して実行する手順であり、この監査では実行していない。実行直前に現在の分類・Git状態・使用中プロセス・元SHA/同一性・アーカイブ全内容を再確認する。

完全な監査JSONは `build/artifact_cleanup_audit_20261020/audit.json.gz`、要約は `summary.json`、候補の現物SHAは `candidate_sha256.json`、レポート圧縮のSHAは `audit_report_storage.json` に保存。いずれもbuild内のGit管理外。

```sh
gzip -dc build/artifact_cleanup_audit_20261020/audit.json.gz > /private/tmp/artifact_audit_readback.json
```

運用手順は [ARTIFACT_CLEANUP.md](ARTIFACT_CLEANUP.md)。50,000,000バイト以上の新規Git blob禁止、既存履歴・保管規則、PCM完全一致条件は維持する。

補足：`du -sk` の集計はresultsが60.924 GB、buildが30.830 GB。各パスの割当量合計とはハードリンクの数え方等で差がある。diskutilはDiskManagementを利用できず、APFS容量プール境界と共有実体は未確認。英字接尾辞を含むphase8a/9a等も個別集計し、同じ実測snapshotから表示を検証した。初回snapshotもaudit_initial_grouping.json.gzとして保管する。

監査後に作成したGit管理外の監査記録は合計32.3 MB。上の容量表はこれらの新規出力を作成する前の測定値。最後の空き確認は20.191 GB（OS活動等を含む）で、既存成果物の解放実績とは区別する。
