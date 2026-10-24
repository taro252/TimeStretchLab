# checkpoint試験の失敗解消

追加したmono16秒素材に対し、既存の肯定試験が要求した0.50→0.40の
`Applied`が成立しなかった。旧5674と候補を同じ素材・要求位置で再実行すると、
両方とも`NoSafeInterval`で、Map値も一致した。長い結合イベント内に安全な
動的適用区間がない負例であり、復元によるMap破損ではなかった。

安全条件を緩めず、元のmix素材とstereoの肯定試験を維持したうえで、
この素材に対応する明示的な安全拒否・復旧試験を追加した。

| 最終確認 | 期待／実施 | 結果 |
|---|---:|---|
| 元mix、stereo44.1kの肯定試験 | 2／2実行 | PASS。固定・動的復元、Map、全suffix一致 |
| 不適合速度Mapの拒否と旧PCMの保持 | 1／1ケース | PASS |
| 拒否後の同速度Duplicateと旧PCMの保持 | 1／1ケース | PASS |
| 旧実体を破棄した後の明示0.40倍固定Exact再準備 | 1／1ケース | PASS |

負例3ケースは1回の専用実行に含む。旧0.50倍のclone suffixは計3,039,232
フレーム、新0.40倍は全1,920,000フレームを独立固定RAWと全バイト比較した。
元owner側の旧suffixも照合する。NaN/Inf、フレーム数、チャンネル順を別に検査する。
拒否前後のDSP・生成／公開位置・Map root・履歴の不変性も要求する。

肯定側のPCM参照は元の合成実体であり、独立凍結RAWの比較は負例側と新0.40倍に
対して行った。明示Exact復旧はPhase57の別合成実体を作る下位層試験で、公開seekの
別request IDを観測した試験ではない。最大2実体はこの試験のスコープ構造で確認し、
製品Engineのowner数は別のnative回帰・終了監査で実測する。

製品が動的要求を自動的にExactへ置換する変更ではない。新速度の固定Exactは
別の明示操作として検証し、旧checkpointを異速度へ使い回さない。

このcheckpoint再実行時のソース台帳SHA-256:
`bfa05533e0d5bef0f5543a09a40e5ee181111bf4e557ca066310ef8f779c7688`。
基準commitは`5674bd982d98caacaa3e87cdeae5bfc0b01c66ef`。
候補は未commitであり、基準commitだけを修正版の識別子にはしない。
`build_final_03/BUILD.json`で新たにビルドした実行体を使用した。

その後の境界待機だけのCV試行は全体CPU悪化により不採用とした。
続く有界timer候補のソース台帳は
`0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e`。
checkpointのソース・実行体・共有DSPは全バイト不変で、archive03／timer_archive05で
対応を照合する。旧実行を最新ソースでの再実行とは記載しない。

独立固定oracle:
`de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。
由来は`results/phase62_fix/recipes/oracle_manifest.json`で、候補DSPを再リンクして
参照にしていない。Planの検算と固定DSPのRAW照合は別の検査である。

証拠は`build/performance_response_20261023_01/`内の次の新規runへ保存した。

- `checkpoint_fixture_repro_02`: 旧／候補×3素材の6実行。旧失敗の同条件再現。
- `checkpoint_positive_final_02`: 最終ビルドの肯定2実行。
- `checkpoint_rejection_final_01`: 3ケース、参照のSHA・生成コマンド・最終統計。
- `final_source_03/SOURCE.json`、`final_archive_03/ARCHIVE.json`: 全ソース／実行体のSHA。

元の`units_final_01`の失敗や、診断driver初回失敗、途中のコンパイル失敗は保存した。
後の成功件数でこれらの履歴を上書きしない。再実行は
`recipes/run_checkpoint_rejection.py --build-record BUILD.json --output NEW_DIR`を使う。
この結果を実時間性能、任意素材での動的適用、FastLocal品質の承認には流用しない。

## 同構成Debugの追加確認

timer05ソースのDebugでも、mix／stereo肯定2fixtureと計画52項目が通過した。
追加の負例にRelease O3参照を渡した`debug_checkpoint_final06`はPCM bit差でFAILと
して保持する。参照を製品コードから再生成せず、保存済みの凍結Debug oracle
`4ee8f3d61cab5aa7d8b39cb148525d7d81a65061efdfe3ce50d4cdc66f637f3f`
（既存manifest `678af349f94c4232293b14af9dfc023f1ba7c239811b27b578d52bc9780f16be`）を
確認して、`run_debug_checkpoint_rejection.py`で別runへ再検査した。
両方ともarm64、`-g`、最適化指定なし、NDEBUGなしである。

`debug_checkpoint_final07`は3/3ケース完了、全suffix／新固定Exact全PCMのbit・長さ・
有限性が一致した。失敗は異なる最適化構成を比較したもので、同構成のcheckpoint状態
破損は再現しなかった。Releaseの成功をDebugへ転記した結果ではない。
元のO3対O0失敗を削除せず、厳密な比較基準も変更していない。

## 最終設定08への限定再利用

08の完全ソースSHAは`b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
05との差はnative headerのstage hash既定ONへの復元だけで、下位Phase57の既定ONは不変。
`build_native_default_08/BUILD.json`の49targetビルド成功後、checkpoint実行体の現在の全byteを
再hashし、03／05の保存実行体とSHA
`fde87c54ad0b19c0906fe8ffe54230cac968d6e3038e9422f6dfb3fc06bb7287`
（579,352B）が一致することを確認した。上のRelease肯定2件／負例3件は同一実行体に
対応する過去実施証拠として再利用し、08で新たに実行した件数には数えない。
checkpointのdigest設定はcloneで継承し、異なる設定のrestore／captureは引き続き拒否する。
この下位層証拠は、既定設定の変わった08 nativeの応答・CPU・RT測定の代用にはしない。

## 容量復旧後の現行08再実行

`checkpoint_native08_recheck_01`は現行08の成功済みRelease buildから3/3ケースを
新たに実行しPASS。独立oracle・入力・既存RAWのSHAを再検証して再利用し、新規参照生成は0。
元実施の件数を付け替えず、`recipes/run_checkpoint_saved_raw.py`と新EXPECTED/SUMMARYへ保存した。
隔離09／probe10の同3case PASSはそれぞれ別sourceであり、CPU採用の承認ではない。
