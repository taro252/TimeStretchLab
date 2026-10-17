# Phase 60 A/B実機比較

承認Phase54 SHA `039592e59cc1a525b495e38d3cedeb6c050792b1` と、Phase60の実験APIを同じWAV・速度・preset・出力装置で別々に実行する。旧ライブラリは承認ソースをGitからそのまま取り出した独立CMake graphで構築し、同じプロセスへ新旧DSPを混在させない。`--engine=legacy` は承認版ホストへexecで置換する。旧ビルドがなければ明示エラーであり、現行Legacyへ代替しない。

`--engine=legacy-current` ではこのcheckoutの既存製品経路を実行する。再生エンジンの種類はLegacyのままで、承認版とのビルド版差を明示する指定である。Phase60をリンクしたMerodoa開発版のLegacyに対応する。既定は承認版legacyであり、アプリの既定設定には影響しない。

## 実行

```sh
python3 -B scripts/phase60_build_legacy.py
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64
cmake --build build --target phase60_playback_compare -j3
./build/phase60_playback_compare /absolute/path/input.wav \
  --engine=legacy --preset=candidate --speed=1.00 --out=build/phase60/my_legacy_01
./build/phase60_playback_compare /absolute/path/input.wav \
  --engine=progressive --preset=candidate --speed=1.00 --out=build/phase60/my_progressive_01
```

同時に起動しない。各出力先は新しいディレクトリとし、以前の失敗を上書きしない。自然EOSまで進み、`summary.json`、session別診断、callback履歴を保存する。ユーザー音源をGitへ追加しない。既存のCoreAudio既定装置を使用し、装置レートやbufferを勝手に変更しない。比較する両実行のdevice ID/rate/bufferを確認する。

`--actions=/absolute/path/actions.csv` で次の壁時計操作列を渡せる。先頭行はヘッダー、同じ時刻の複数速度要求も可。準備/解析の進み方で適用位置が変わり得るため、予定時刻と実際の計画を別記録する。

```csv
at_s,action,value
0.5,speed,0.41
0.5,speed,0.49
1.0,pause,0
1.2,resume,0
2.0,speed,2.00
3.0,stop_play,0
```

`speed/pause/resume/stop_play/stop/route` に対応する。routeは模擬試験。操作時刻の基準は最初のplay受付復帰後なので、旧同期playと新非同期受付の差を含む。準備中に速度要求が届けば、新APIはStopped/ID0で拒否する。厳密な論理位置のPCM回帰は別の固定参照試験で行う。

`--restarts=1` は自然EOS後のPlayを追加する。`stop_play` は先頭から新セッションを準備する。既定は0回、速度変更なし。`--capture=...f32` はProgressive専用の任意診断で、ホスト側が事前確保した最大512MiBへゲイン前の受信PCMだけをコピーする。無音補填をPCM正確性へ混ぜない。Legacyの `--verify-pcm` は既存workerで公開済みPCMのSHAを計算する。両者の観測点・負荷は異なるので、CPU/RSS比較は通常計測と検証付き計測を別に示す。

## 今回の入力

ユーザー指定の `08 Esprit.m4a` はAAC、44.1kHz、stereo。元ファイルを変更せずmacOS afconvertでFloat32 WAVへ変換した。最初の出力はWAVE_FORMAT_EXTENSIBLEで、既存読取り契約どおり旧/新とも再生前に拒否した。その原本を残し、`scripts/phase60_prepare_wav.py` と同じ方法でdata chunkを1ビットも変えずに通常RIFF/IEEE_FLOATへ包み直した。対応WAVは13,706,110入力フレーム、約310.796秒、SHA-256 `1fee0c9c5dd3302c02fe7f7215635a4478e0d058d4d636094998d92d29d65963`。保存先・PCM payload SHA・元M4AのSHA・変換/包み直し手順は `results/phase60/INPUT.json`。

当時Merodoaが使用したデコード済みWAV、そのSHA、出力装置名は未提供である。ユーザーログのgenerated=17,831,214とも今回の入力長は異なる。したがって、このM4Aから得た同一WAVによるA/Bは実施できるが、当時の80,765不足とまったく同じWAV/操作履歴/装置を再現したとは判定しない。`pcmBudget`は別の媒体キャッシュ容量エラーとして扱う。

## 計測と判定

最初のAPI要求から先頭PCM callbackまでをMach時計同士で計算する。入力SHAの外側検証と診断バッファ確保は要求時刻より前であり、初回プロセスでもOSファイルcacheを温める。この試験のColdは新プロセス・解析cache未使用の初回という意味で、OS cacheを排除した測定ではない。

通常計測は参照PCMの生成を重ねない。音声子プロセスの終了後だけ独立参照を計算する。ビルドや他のDSP試験とも同時実行しない。process CPU、プロセス生涯Peak RSS、Progressive終了時のDSP worker CPUを分ける。旧版に存在しないworker期限/常駐量等はnull。C++ newとOS faultも未測定を0にしない。

`measurement_completed`、FIFO/書込み/コールバック、時計、worker期限、PCM、物理出力を別に判定する。供給の不足が1フレームでもあればFAIL。Endedを供給成功へ読み替えない。PCM比較は全Float32生ビット、長さ、チャンネル順、SHAが一致することを要求する。動的計画は変更前の独立Phase39/Phase36参照へ実際のFrontierを再現する。新API同士の比較だけを独立参照にしない。

実測値・全失敗・範囲は `results/phase60/REPORT.md`、`native_representative/summary_reviewed.json`、`native_user_canonical/summary.json`。開始前の拡張WAV拒否は `native_user/summary_reviewed.json` に別保存した。元の集計で空集合のall()が成功になる問題も訂正し、必須件数・PCM比較数が揃わない場合は未測定/FAILとする4試験を追加した。元JSONを上書きせず、訂正済み集計を正とする。

manifestに入力、装置、Release構成、実行体SHA、コマンドと保存先を記録する。代表回帰と今回の限定成功は、Phase59 Fix 2のGate 2、過去の旧FIFO失敗、時計異常、物理loopback未実施を変更しない。
