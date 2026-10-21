# Phase 62 D08: descriptor 64枠の保持範囲

## 対象と判定の範囲

本書は `Phase58RealtimePipeline` の `LoopPcmDescriptor`（周期番号と境界補正に使う先頭・末尾のPCM値）を64枠で保持できる理由を、実装の供給量と消費順から導く。対象は既存の単一producer／単一audio consumer契約を守るLoop再生であり、callbackは最大4096フレーム、完全な出力周期は512フレーム以上である。

**最古の必要周期 `c` から最新公開周期 `d` までの距離は、安全側の上限で `d-c <= 44 < 64`。** 44は到達可能な最大値を実測した値ではなく、実装が許す供給・消費の量から得た上限である。同時に保持対象となり得る周期は両端を含め最大45個となる。レビュー中の未証明の「46」を根拠として使用していない。

この結論は正常な環状枠の再利用に関する不変条件である。実producerを64周期以上追い越させた統合試験のPASSとは呼ばない。別途、実際の読出し処理が異なる周期の値を拒否する下位試験を `tests/Phase62DescriptorInvariantTests.cpp` に設ける。実行結果と最終判定は今回のrunのSUMMARY／CONTROL_COVERAGEで記録する。本書と試験コードの追加だけでは実行済みPASSにしない。

## 実コードに対応する前提

| 条件 | 実装の接続点と理由 |
|---|---|
| FIFO最大16,384フレーム | `RealtimePipeline::Impl` の `fifo(input.channels,16384)`。`Phase14AudioFifo::write()` は未消費領域への上書きを拒否する。Baselineの先行量12,288も、この大きい方の上限に含まれる |
| 未公開pending最大2,048フレーム | `repeatWithEngine()` の `pending[2][2048]`。`ProgressiveSynthesisEngine::advance()` の1回のsink呼出しは最大2048。`pendingCount` が残ればflushまたはwaitへ進み、次の生成・cache読出し・次周期への進行を行わない |
| 完全周期512以上 | `seekAnalysis()` と `repeatWithEngine()` が `loopOutputEnd-repeatBegin < 512` を拒否する。短い初回C→Bは完全周期と区別する |
| callback最大4,096フレーム | `render()` がLoop中の `n>4096` を `CallbackLimit` として拒否する。`periodSpan()` はさらにBと補正窓で分割する |
| 各sourceにconsumerは1つ | `RealtimePipeline`／`Phase14AudioFifo` の契約。`render()` のbusyフラグは同時実行を拒否する。制御側から同じFIFOを並行消費しない |
| 初回区間は `[C,B)` | `enableLoopReuse(a)` は `a<=seekInput<B` を要求し、Map内の `outputStart` から初回Bまでだけを公開する。丸めで出力が空の場合もあり得る |
| 採用後の動的周期は最終周期 | 動的／固定B確定後、`repeatWithEngine()` は `terminalLoop() && cycle>=loopTerminal.cycle` で終了し、同じownerから後の周期を公開しない |
| 読出し結果は所有する値 | `ValueMailbox<T>::read()` は `std::optional<T>` のコピーを返し、return前にhazardを解除する。`loopPcmDescriptor()` と共通の `readLoopPcmDescriptor()` は完全な64bitのcycle一致を検査する |

FIFOのread／writeを別々に採った診断標本を、同時刻の対として扱う証明ではない。以下は各書込み・読出しの順序と、未消費容量の不変条件についての議論である。

## 座標と初回部分区間

Map内の出力位置ではなく、そのownerがFIFOへ渡すPCMの累積フレーム位置を使う。固定の完全周期長を `L>=512`、初回C→Bの長さを `R0=B-outputStart` とする。Aから開始すると `R0=L`、途中Cからは `0<=R0<=L` となる。通常ownerのKeepPosition自己反復も、`repeatBegin=0` と同じ式に接続される。

周期開始位置を次のように定義する。

```text
C_0 = 0
C_k = R0 + (k-1)*L    (k >= 1)
```

`R0>0` のcycle 0は部分区間であり、512以上とは仮定しない。`R0=1` でも以下の証明は成立する。

`R0=0` ではPCMを持つcycle 0が存在しない。`Impl::repeatCycle(0)` は `1+(0-0)/L=1` を返す。`normalizeEmptyEntry()` はrendererの表示位置をBからAへ移し、初回の空区間を自然周回として加算しない。producerは空のcycle 0を終え、cycle 1のdescriptorを先行公開できるが、consumerが必要とする最古のdescriptorもcycle 1である。空区間を512フレームとして数えたり、空の周期を無制限に挿入したりしない。

## 最新公開descriptorの先行範囲

時刻`t`における累積FIFO writeを `W(t)`、readを `R(t)` とする。FIFO容量から常に `W(t)-R(t)<=16384` が成り立つ。

最新のdescriptorがcycle `d`を示すとき、その周期開始 `C_d` は次の上限を持つ。

```text
C_d <= W(t) + 2048
```

この上限は、公開の2経路と初回接続をすべて含む。

1. **DSPからBを生成したとき**: `repeatWithEngine()` のsinkはBの末尾値を採ってdescriptorを公開する。前のpendingは処理済みであり、この生成ブロックの未公開部分だけが残る。Bまでの累積位置は `W+pendingCount`、`pendingCount<=2048`。周期開始はB以下なので `C_d<=W+2048`。初回が空でも、先に生成して破棄するA〜Cは累積FIFO位置へ加算しない。
2. **cacheの次周期を先行公開したとき**: `generatedEnd` と `pendingCount==0` の後にcycleを増やし、cache経路は次のPCMを作る前にdescriptorを公開する。この時点の新周期開始は `C_d=W`。次周期の先行公開を1周期分余計に加算する必要はない。すでに `C_d<=W+2048` に含まれる。
3. **通常ownerから自己反復へ接続するとき**: 既存FIFOを維持し、`repeatPublished=published-outputStart` と既存 `seekPcm` を引き継ぐ。`generatedEnd` の初回descriptorも、Bまでに未公開なのは最大2048のpendingだけであり、同じ上限になる。

DSPの生成位置やcache再構成の作業位置は、それ自体を累積FIFO writeとしない。cache再構成用sinkはPCMを公開せず、descriptorも発行しない。cacheから生成中へ戻ってもpendingの既存内容を保持する。過去に公開されたdescriptorについてもwriteは単調に増えるため、lookup時点の `W(t)` に対してこの上限を使える。

動的変更がcycle `d` のBを変更した場合、周期の開始 `C_d` はそれ以前の固定周期で決まる。変更後Bのdescriptorを公開して、その周期でproducerは停止する。変更後の周期長を使って複数の新周期が詰め込まれる経路はない。`FixedBoundaryCommitted` でも同じ最終周期の扱いとなる。

## 最古の必要周期からの最大距離

あるsourceでcycle `c` を取得した直前の累積readを `r` とする。`renderPeriod()` はdescriptorをpull前に取得する。一方、入口混合の `renderPcm()`／`correctEntryPeriod()` はcycleをpull前に記録し、descriptorはpull後に取得する。この後者も含め、descriptorの値コピーが終わるまでに、そのsourceのreadが進む量は最大callback長4096以下である。

```text
R(lookup) <= r + 4096
C_d <= W(lookup)+2048
    <= R(lookup)+16384+2048
    <= r+4096+16384+2048
    =  r+22528
```

producerが速く動く、またはcallbackが途中で長く中断されても、同じsourceのconsumerはこのlookupが終わるまでさらに先へ進めない。FIFOが満杯になればproducerも止まるため、経過時間は上限を増やさない。

`d>c` の場合、lookup対象cycleの残りは正の整数フレームであり、`C_(c+1)-r>=1`。初回cycle 0でも `R0-r>=1` で十分である。その後の、最新公開cycle `d` の開始までに完了した各周期は512以上である。従って:

```text
C_d-r = (C_(c+1)-r) + (d-c-1)*L
      >= 1+(d-c-1)*512

1+(d-c-1)*512 <= 22528
d-c <= 1+floor((22528-1)/512) = 44
```

`d-c=45` なら最小でも22,529フレーム必要なので上限を超える。同じ枠を上書きする `d-c=64` なら少なくとも32,257フレーム必要となり、成立しない。FIFOの先行量、未公開pending、callbackが解放した領域、短い初回区間、次周期descriptorの先行公開を同じ累積座標で数えた結果である。

## old/new source併用と値の寿命

入口混合はold/newそれぞれの `RealtimePipeline`、FIFO、64枠のringを持つ。`render()` は双方について `periodSpan()` を適用し、`renderPcm()` はそれぞれpull前にそのsourceのcycleを取得する。各sourceがこのcallbackで消費する量は4096以下である。2つのringの周期距離を足す必要はない。それぞれ独立に44以下となる。

`correctEntryPeriod()` はdescriptorの `last` を局所の `std::array<float,2>` へコピーする。`renderPeriod()` も `descriptor->last` を局所の配列にコピーする。どちらもmailbox内の参照・ポインタを保持しない。次のcallbackで必要な末尾値は `RenderTarget::previousTail` へ値としてコピーし、先頭／末尾補正の監査値も `ProgressiveOutputSpan` に値として格納する。後続callbackが古いring枠を参照し続ける経路はない。

従って、最古の「必要なcycle」は今回値を取得しているcycleでよい。以前のcallbackが処理したcycleまで保持範囲を延ばす必要はない。所有者の寿命は別の契約であり、handoff完了と `inRender==0` の確認後に通常側で退役する。

## 維持する試験と限界

新規下位試験は、製品 `loopPcmDescriptor()` と同じ `readLoopPcmDescriptor()`、同じ `ValueMailbox<LoopPcmDescriptor>` と64枠の型を使用する。

| 試験ID | 検査内容 |
|---|---|
| `D08.empty_unpublished` | 未公開枠をcycle 0として誤受付しない |
| `D08.slot_wrap_identity` | 3回の正常な環状枠再利用で現cycleの値が一致し、同じ枠の過去／未来cycleを拒否する |
| `D08.forced_stale_cycle_rejected` | 下位で意図的に `c+64` を同じ枠へ公開し、`c` を実読出し処理が拒否する |
| `D08.descriptor_value_lifetime` | 取得した値コピーが、その後同じmailbox枠を9回再利用しても変化しない |
| `D08.two_source_independence` | 別ringのold/newそれぞれで44周期先まで公開しても、各最古cycleが保持される |
| `D08.capacity_bound` | 正の残り1〜512とcallback進行の境界値について上の整数不等式を検査し、45／64周期を拒否する容量差を確認する |
| `D08.full_width_cycle_identity` | uint64_t上端付近でも現cycleが一致し、同じ枠の過去cycle／32bitだけ一致する過去cycleを拒否する |

`D08.capacity_bound` は証明の整数計算を検査する下位試験であり、実DSP／renderer試験の代用ではない。実際の短い初回区間、空R0、512周期、最大4096 callback、old/newが独立にBを跨ぐ入口混合は、既存 `Phase62DynamicBoundaryTests.mm` の `R0`／`B_minus_1`／`phase_first` 等、`--period512`／`--old-near-b` で維持する。正常な多数周回は `Phase62FixRenderTests.mm --long`（4100周期）の別証拠である。4100正常周回を異常追越しの証拠へ転記しない。

この上限は、任意にproducerを停止させた場合のdescriptorの準備完了や、PCMの不足がないことまで証明しない。未準備／cycle不一致は既存の `NoPrepared` として安全に拒否する。単一consumer、FIFO容量、pending上限、callback上限、完全周期下限、終端後に同ownerが再反復しない条件を変更するときは、本書の証明と該当試験を再評価する。通常速度変更等の別経路の履歴上限を、ここから到達不能と一般化しない。uint64_tの累積カウンタ自体のオーバーフロー後の動作も、この有限実行の証明対象に含めない。
