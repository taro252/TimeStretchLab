# Phase62 Fixの証拠と再実行

原本は `/Users/taro252/Docker/TimeStretchLab/build/phase62_fix/run_01`。既存の失敗・中断・PCMを上書きしない。最終固定版は `final_v9`。品質スクリプトだけを修正し、CMake／製品／C++試験はfinal_v8と同一。release／debugと完了済み7スイートは、SHA不変と依存関係の明示監査を伴う元のF8ビルド／証拠へのリンクである。元のソースSHAは書き換えない。その他の途中版と区別する。最終ソースのCMakeLists.txt／src／tests／scriptsはSOURCE_MANIFEST.jsonで照合する。時計検査の実装が同じ途中版で発生した時計異常も保持する。

## ソースと実行体

開始点は `d25433c88a1bae83b89168a26f1c6c9d8053a644`。新しい作業コピーに、ARTIFACT_MANIFESTが指す `final_v9/frozen_sources.tar.gz` を展開してSOURCE_MANIFESTと照合する。既存の作業ツリーを上書きしない。現ファイルからの確認例は以下。

```python
from pathlib import Path
import json, sys
sys.path.insert(0, 'scripts')
from phase62_evidence import source_manifest
actual = source_manifest(Path.cwd())
expected = json.loads(Path('results/phase62_fix/SOURCE_MANIFEST.json').read_text())
assert actual == expected
```

固定oracleは `build/phase61/oracle_release_v1/phase61_frozen_reference`。SHA-256は `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`、arm64。元ソースは `ec087019626d9ff0d9f157245729b74ddb6847d7` のPhase36。再ビルドの詳細は同ディレクトリのmanifest.json／compile.log／link.logに保存されている。既存oracleを再ビルドで置き換えない。復元時も別の新規出力先にする。

全検証実行体はarm64を明示する。Intel版Python経由の既定選択に任せない。各スイートはconfigure→build→lipo検査が通った場合だけ実行し、source変更や必須生成物欠落を成功にしない。Release／Debugは別の新規ビルド先を使う。最終実測の各コマンド、終了値、binary／input／oracle SHAはEXPECTED／LEDGER／BUILD_PROVENANCEを参照する。

## 主スイート

下記のNEWは未使用の出力先とする。Pythonはarm64のNumPy対応環境を推奨する。今回使用したPythonとコンパイラー、OS、ハードウェア情報はENVIRONMENT.jsonを参照する。

```sh
python3 -B scripts/phase62_verify.py --suite ctest --configuration Release --build build/phase62_fix/NEW/release --output build/phase62_fix/NEW/ctest_release
python3 -B scripts/phase62_verify.py --suite ctest --configuration Debug --build build/phase62_fix/NEW/debug --output build/phase62_fix/NEW/ctest_debug
```

同じ引数形式で、suiteをexact、golden、pcm、pcm161、native、controls、long、step1へ替え、outputはそれぞれ別の新規先にする。Debugのnative／controls／longもconfigurationとbuildを変えて実行する。操作・同期の64フレーム試験は親プロセスが装置バッファーの復元まで確認する。

追加条件は `scripts/phase62_fix_additional.py` のsuite=offline、short、longA、clock、deadline。引数はbuild／output／configuration。clockは装置レートを測定前後で復元し、通常非ループの開始10回×2入力も含む。実行できない装置設定や失敗した試行を、成功条件へ置き換えない。

独立境界処理と試聴WAVは `scripts/phase62_fix_quality.py --build 新Release先 --output 新規先`。NumPyを使う。176ケースを事前宣言し、RAW、実render加工後PCM、独立libm fmaf数式を全ビット比較する。10／25／100ms窓は、検証済み定常周期の延長で構成する。物理的な録音ではない。

## 大容量入力と追加測定

- 300秒入力：phase57_study.fixtureで48kHz Stereo PCM16・boundary・2秒を生成し、そのPCMを150回反復する。WAVの書式とSHA、ブロックSHAはlongA/INPUT_RECIPE.jsonに保存する。A=0／30／270秒、100／500ms、2倍、両方式を各100周測定する。
- 同条件比較入力：3秒48kHz Stereo PCM16のboundary。SHAは `7ec3f2aa3c2e746643d24cfbda653bdde6eaedc9dd82be6a9ca7159372fe26ce`。既存入力を変更しない。欠けている新しい作業コピーに限り、同じfixtureレシピで新規生成しSHAを照合する。
- 後半Aの独立RAW：final_v9/deep_independent.py、deep_long_seed.py。既存の最終再利用試験実行体を使い、300秒全長oracleと12短区間＋2長区間を比較する。長区間はキャッシュ上限を超える10秒区間で、保存点復元も検査する。
- Exact参照の非有限値：exact_finite.py。112組の全長参照を新規生成し、Exact896が記録した参照SHAと同一であること、全サンプルのNaN／Infが0であることを確認する。
- 同条件1000周：paired_1000.py。修正前arm64 binaryと最終arm64 binaryを直列実行し、入力SHA、A/B、速度、方式、装置ID／48kHz／512、実周回数を照合する。順序は旧→新、1走行ずつ。周期は旧L−N／新Lと異なるため、wall時間もその契約に従って異なる。
- Sandbox：sandbox_run.py。最終署名アプリで、NSOpenPanelから既知の入力1ファイルと新規sandbox_ioフォルダーだけを選ぶ。grant外の既存ファイル拒否、scope開始、100ms反復2方式、13障害検査を記録する。元音源はscope中に1回デコードする。MerodoaのTCC拒否・期限切れbookmarkの代替ではない。
- Clear後の時計：post_clear_clock.py。全native期待台帳から対象を列挙し、解除後の末尾256callbackと全spanを独立再計算する。失敗・欠落を除外しない。
- FD寿命：fd_lifetime.pyとfd_lifetime.cpp。最終Releaseライブラリーへ別ホストをリンクし、親pipeline破棄後、2所有者、1000周期後、最後の所有者破棄後の入力／private snapshot FDを実測する。これは非Sandboxの所有権検証であり、Sandboxのgrant・MerodoaのTCC／bookmarkとは別に扱う。
- 試聴用比較：listening_pack.py。11素材・2方式・100ms／約2秒区間の2倍速44条件について、検証済み定常周期から最低10秒のRAW／加工後WAVを同じゲイン0.5で用意する。無音追加や重畳はせず、試聴・実音響を合格にしない。
- 境界方式の比較：boundary_methods.py。検証済みRAW／現行加工と、周期Lを保ち窓の両端を0へ落とす未実装のスカラー包絡案を比較する。現行のインパルス100ms・0.4倍で10ms RMSが約+13.14dBとなる条件を含む6条件に、同ゲイン0.5・最低10秒の3方式WAVを用意する。ゼロ終端案には音量低下・アタック消失の危険があり、実装・採用・主観承認を意味しない。
- 範囲内seekの追加：inside_seek.py／inside_seek_native.cpp。同じ最終製品ライブラリーへ別ホストをリンクし、44.1k mono PCM16と48k stereo PCM16×2方式で、I=A+(B−A)/2への実移動、B後の元A復帰、0.75倍の独立全長RAWとの全ビット比較を行う。B直前の一般対応はこの試験の対象にしない。
- 開始時計の追加反復：clock_startup_extended.py。未解決の開始時刻異常を調べるため、ループ要求なし・Candidate0.4で44.1→48／44.1→44.1／48→48を各100回起動し、全300試行の記録を独立再計算する。装置レートを毎条件の終了時に復元する。成功しても元の異常を解決済みにしない。
- 既存実曲ピアノ：piano_quality.py、piano_waveform.py、piano_listening_pack.py。Phase2のpiano_original.wav（48kHz stereo Float32、30秒）を別入力として、16条件の独立RAW／加工一致、帯域・定位・位相、4条件の最低10秒比較WAVを作る。既存REPORTを出所とし、楽器の収録方法までは独立確認していない。人工piano_syntheticと混同しない。
- 追加波形解析：waveform_analysis.py。176キャプチャの局所差分、左右定位・位相、1秒文脈の帯域量と比較図を作る。スペクトルも定常周期を延長した解析であり、試聴や実音響の承認ではない。

これらの追加ドライバーは最終ソースを変えず、前工程の完了まで待って直列実行する。実際のドライバー原本とSHAはARTIFACT_MANIFESTに記録する。raw／WAV／trace／binary／archiveはGit管理外に保つ。ローカル原本全体を別ストレージへ保存すれば、全artifact manifestで同一性を検証できる。再実行したCPU、RSS、時刻の値が元の実測と同じになる保証はない。別試行として保存する。

## 小さな再生成コード

実行した追加ドライバーと補助C++ホストは `recipes/` に同じバイト列で保存し、RECIPE_MANIFEST.jsonで原本と結ぶ。固定されたfinal_v9等のパスは、この実測原本を指す。再実行では新しい作業コピーか未使用の出力先へ変更し、既存証拠・報告を上書きしない。F8証拠を再利用する最適化ドライバーは既存証拠に依存する。原本がない環境では、先に上記の公式スクリプトですべての主スイートを新規実行し、それへ追加ドライバーを接続する。

固定oracleのバイト列は、Git管理外のfinal_v9/frozen_oracle_backupにも同じSHAで複製する。元のoracleは置き換えない。元のmanifest／compile.log／link.logの小さなコピーはrecipes/oracle_*を参照する。再ビルドで同じbinary SHAにならない場合は、元のoracleと同一と扱わない。

## 保存済み失敗と描画の再生成

制御したpaired_1000の旧版は次周期PCM不足またはcallback上限超過という診断で途中停止した。旧版の完走CPU比較は不成立として残し、初回保存の成功1000周をこの対照走行の代わりに付け替えない。FAILURE_ANALYSIS.jsonと元の台帳・診断文を参照する。

波形3スイートは数値計測後、描画ライブラリー未導入により図生成だけが失敗した。元の失敗台帳を残し、figure_repair.pyが元の描画関数をそのまま読み、新規出力先で図だけ再生成する。専用plot_dependenciesへmatplotlib 3.10.7を導入し、既存NumPy 2.3.5を先に読み込む。依存パッケージ全版はrecipes/plot_requirements.txtとPLOT_DEPENDENCIES.json、実コマンドはfigure_repair台帳を参照する。新しい環境では数値計測と描画を混同せず、同じ版のNumPyを用意してから未使用の先へ出力する。元の音声試験やRT失敗を上書きしない。

original_phase62_audit.pyは旧results/phase62/ARTIFACT_MANIFEST.jsonの全9678原本・2,850,330,692バイトをSHA照合した。最終結果はORIGINAL_PHASE62_AUDIT.jsonにあり、旧Phase62の原本を変更していない。

最終実行体監査はfinal_binary_audit.py。主試験後のSandbox署名によりReleaseアプリ1件のSHAが変わる。元の100件不変監査を署名後まで延長して解釈しない。他99件不変と署名後SHAの一致をdependency_audit_after_sandbox.jsonで確認する。
