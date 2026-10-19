# 停止中速度変更の証拠と復元

この結果は開始HEAD `406a1fde0b130bbe5ae3ce7a1666cce696db9c99` と本件の未コミット差分を検証したもの。確定Git SHAの合格として扱わない。SOURCE_MANIFEST.jsonの各ファイルSHAとバイナリSHAを使用する。

- 原因照合：CAUSE_AUDIT.json
- ソース・実行物：SOURCE_MANIFEST.json
- 実際のコマンド・終了値：COMMANDS.json
- 全644件の比較位置・PCMフレーム数・参照spanハッシュ：PCM_RESULTS.json
- 独立参照648ファイルの保存場所・SHA-256・元の生成コマンド：REFERENCE_MANIFEST.json
- 集計・時間・資源：SUMMARY.json
- 50,000,000バイト監査：BLOB_AUDIT.json
- 全証拠ファイルの場所・サイズ・SHA：ARTIFACT_MANIFEST.json

大容量データと途中結果は削除せず、Git管理外のbuild/に保存している。参照を再利用した場合、manifestのphysical_originが実体を指す。コピーや退避はその実体も含めて行う。

元データを復元する場合は、現在のソースがSOURCE_MANIFESTの内容と一致することを確認し、docs/PAUSED_SPEED_CHANGE_VALIDATION.mdのコマンドを新しい出力先で実行する。verify_paused_speed.pyのfixture関数で時刻識別可能な入力を生成し、phase61_freeze_reference.pyで記録された旧Phase36をリンクした独立参照を再生成する。再開頭部の実測はネイティブ観測メモリで比較しておりファイル保存していないため、再取得には実機で再実行する。

集計の生成手順はrecipes/collect_evidence.py。リポジトリルートを作業ディレクトリとして使用する。元の音声試験結果やGoldenは上書きしない。

統合時は同内容を確定した完全Git SHAと証拠を対応付け、Merodoaブリッジをその版で再ビルドする。snapshotのstoppedSpeed/resumePending、UInt64の要求ID、resumeの受付とPlayingの区別を接続する。
