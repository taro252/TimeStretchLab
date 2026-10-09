# Phase 12 音源・Golden WAVの保管設計

## 現状と保管の境界

Golden WAVは `results/phase12/golden/` に存在し、ハッシュ付き [`manifest.csv`](results/phase12/golden/manifest.csv) と [`baseline.json`](results/phase12/golden/baseline.json) はGitに保存されている。一方、WAVは `.gitignore` によりGit管理外である。**2026-10-10に、別媒体のUSB上へAES-256暗号化イメージを二次保管し、USBからの復元試験を完了した。** 対象、ハッシュ、復元結果は [`results/phase13/CUSTODY_REPORT.md`](results/phase13/CUSTODY_REPORT.md) に記録する。保管先の具体的なパスとパスワードは公開Gitへ記録しない。

公開リポジトリへ、原曲、切り出した入力、無加工出力、試聴コピー、音声を復元可能な埋め込みデータを追加しない。現在Gitに置くのは設定・手順・ハッシュ・測定値だけ。今後Git LFSを使う場合も、公開リモートへ音源が送られないことを先に確認する。音源の著作権・利用許諾の確認と、非公開保管先へのアクセス権設定は別の運用作業とする。

## 入力の来歴と照合値

以下の元WAVから既存の比較区間をFFmpegで `pcm_f32le` に切り出した。今回、現在の元ファイルから同じ区間を再抽出し、保存済みの `results/phase12/golden/input/*.wav` と**5件すべてバイト単位で一致**することを確認した。ハッシュはSHA-256。元ファイルは現在の個人用 `Downloads` にあり、公開Gitには入れない。

| 用途 | 元WAV | 元ファイルSHA-256 | 区間 | 凍結入力SHA-256 |
| --- | --- | --- | --- | --- |
| MIX | `mix.wav` | `88beb7a0e5819a84f71e608b5250213a983f3c2f8638317e25bc739197fb3d79` | 90〜135秒 | `6cf7cd9ca5dd7206ca8157e610da2ef870ef48625da6b1cfea38763fd2dff157` |
| Vocal | `vocal.wav` | `3e5dc7885189823e2abadcbde624a903f908d7c64aac0c9096d65bf0d1cb1ee8` | 90〜135秒 | `78278018c95785ca68cf126c30b1e4f76dc24bd25cd35f35785daf14a5e3137b` |
| Bass | `bass.wav` | `04cdfd5a4319ddefe96e8b83cf42bd371ce60b91d1c5bb1ea9dc5e7fa2a1f71a` | 90〜135秒 | `1405fb3051c0efdcd09baa385906af0e317a460493de9f087359f210953afb58` |
| Drums | `drums.wav` | `4ebf35e67a261ef50930e89afe8784549a28666aae17c7e8ef0dd1502863f166` | 30〜40秒 | `9c73c02302497a738e20ca3d68231b2e20967f5ba40a164e1393479f2b71f928` |
| Guitar | `guitar.wav` | `0ca0d007c774ed94acd275566158944ca1c39ee3368749719376ead36a289c1c` | 30〜40秒 | `21a0ae089ef4a1ddc9df1ae1d5e8b7591291dcf6017442fe68efa1dd327ae396` |

元ファイルなしでも、凍結入力5本とビルド環境があればGoldenを再生成できる。ただし現行 [`scripts/phase12_golden.py`](scripts/phase12_golden.py) は旧比較ディレクトリ内の入力WAVと凍結入力を照合してから動く。このため、保管・復元対象には次の**旧比較入力も同じ相対パス**で含める。将来スクリプトを凍結入力だけで実行できるようにする変更は、別途テストしてから行う。

## 非公開アーカイブに含めるもの

1. **必須入力**：`results/phase12/golden/input/` の5本、`results/phase53/real/{mix,female,bass}_input.wav`、`results/phase101/real/{drums,guitar}_input.wav`、`results/phase101/artificial/click_train_input.wav`。重複コピーも復元パスを固定するため保持する。
2. **正本出力**：`results/phase12/golden/raw/` の15本、`results/phase12/golden/anchor_click_050.wav`。現行のハッシュを照合できるようにする。
3. **付随資料**：`manifest.csv`、`baseline.json`、`anchor_diagnostic.json`、この文書、生成スクリプト3本、DSPコードのGitリビジョン。試聴用 `audition/` と `audition_manifest.csv` は保持してもよいが、正本ではなく固定ゲインから再作成できる。
4. **来歴の任意保管**：元の5本のフルWAV。再生成に必須なのは凍結入力だが、原曲との対応確認や別区間の将来検証に必要なら、利用許諾を確認した非公開保管先へ別に置く。

アーカイブは、公開Gitとは別の**アクセス制限された暗号化保管先**と、別の故障領域にある二次コピーを設ける。現在はMac上の元ファイルと別媒体の暗号化USBコピーがあり、後者を読み戻して復元済み。USBとMacを同じ場所で保管すると災害などの同時損失には弱いため、物理的な保管場所と保持期間は運用上別途管理する。公開リポジトリのCIから音声本体を取得・公開しない。保管先や認証情報をこのリポジトリに書かない。復号パスワードを紛失するとUSBコピーを復元できないため、USBとは別の安全な場所に保管する。

## 環境と復元確認

Golden作成時：macOS 26.6.2（build 25G83）、arm64、Apple clang 21.0.0、CMake 4.3.3、Releaseビルド、FFmpeg 8.1.1、Apple Accelerate/vDSP。DSPソースのリビジョンは `276bed754bcfe8c7b0f617e63e1f18b88d48e299`、実行した `build/timestretch` のSHA-256は `d27dfe5ddf1dbc05c9ee96c756e3894be132eabff4e0475287318c413f734500`。後のOS・Accelerate・コンパイラでは浮動小数点のビット一致が保証されないため、**元のraw Goldenを正本として保管**する。

保管完了の判定は次の復元試験を通った場合のみとする。

1. 非公開アーカイブと二次コピーのハッシュを記録し、別ディレクトリへ復元する。元の作業領域へ直接上書きしない。
2. 復元した入力5本、raw15本、補助クリックをmanifest／JSONのSHA-256と照合する。試聴コピーを含めた場合は `audition_manifest.csv` とも照合する。
3. 必要な旧比較入力の相対パスが存在することを確認し、`python3 scripts/phase12_golden.py`、`python3 scripts/phase12_anchor_diagnostic.py` の検証モードを実行する。再生成試験は別コピーで行い、正本のraw WAVを上書きしない。
4. 失敗したファイル、欠けた保管先、権限不足、環境差を記録し、修復後に再試験する。復元試験を通るまでリアルタイムDSP試作の入力基準が確保できたとは扱わない。

ハッシュは一致性の検査値であり、著作権上の再配布許可を意味しない。
