# 性能・応答の調査（2026-10-23）

基準 `5674bd982d98caacaa3e87cdeae5bfc0b01c66ef`。開始時main clean。
作業はcodex/performance-response。Merodoaはc6ed9251、依存f4f0e6187で不変。
新規証拠は `build/performance_response_20261023_01`、旧runを上書きしない。

Progressiveの実経路はmacOS engine→Phase58→Phase57→Phase36→Phase35/FFT/FIR。
Legacyも共通DSPを使う。Exact cold A270の原点からの前置DSPが支配している。
解析待ちだけを解消しても10秒は消えない。先行準備は費用を操作前へ移す。
FastLocal旧78品質FAIL、stereo Ready p95 211.090ms・worker期限1は旧結果として保持。

優先対象はB1/B2重複polar/入力abs/arg、B3内部stage hash、D1途中ONでの
仕事破棄、C3 constructor取消/期限、D3全seek周期走査。
C1はMapの確定prefixを共有し、C2は唯一の解析producerをInputLeaseへ移した。
final待ちだけを削除すると旧render owner停止で解析が永久停止するため、
共有解析の寿命とsuffix/EOS追従を同時に変更した。
各項目の採否・実測は新REPORTへ記録する。

その後C1は不変ページを共有するMapへ、C2はInputLease所有の単一解析producerへ
実装した。C1の72回比較では全Map/Planが一致し、多イベント専用素材の300秒・
速度履歴4件で計画CPU中央値102.208→5.801ms。元のchain300はEOSまでイベントが
閉鎖しないため、増分履歴負荷の実証には使えなかった。専用素材は計画費用だけの
対照であり、既知FastLocal品質やAB性能の素材を置き換えない。

checkpoint追加mono試験の失敗は、旧新版で同一NoSafeInterval・同一Mapだった。
元mixの肯定試験に加え、安全拒否後の全suffixと明示固定Exact復旧を独立RAWで
検査する専用負例を追加した。肯定側のApplied条件は維持した。
最終回帰で見つかった契約v4への試験移行漏れも、旧v3の拒否と全件数を保って
修正した。これら最後の4試験ファイルの変更では製品src/CMake/scriptsは不変。

InputLease監視共有、speed要約、idle seek通知、Clear再ON、Paused準備、
FFT plan再利用は既済。8192 Ready案は撤回済みで、通常leadを維持する。
旧Time Profilerの標本割合を最新CPU秒へ換算しない。

17:48頃に追加編集が消失する事象を確認し、ユーザーは破棄操作なし・復元続行を指示。
消失時diffをOBSERVED_DIFF_DISAPPEARANCE.json、復元差分をrecovered_01へ保存。
以降は各buildの前後source inventoryを確認する。原因は未確定。

長いArmed待機のCV案は待機threadのCPUが減っても全体CPUが悪化したため不採用。
同じ100μs→1msでもengine mutexを取得しない有界timer案は、bfa版とのn3交互比較で
全3組の全体CPUが低下した。基準5674との全面比較とは別の局所差分比較である。
通常再生・AB・Interactiveの最終測定と組み合わせて採否を決め、wakeupだけを
成功根拠にしない。過去の不採用案のsource/binary/生測定も保持する。

## 2026-10-24の候補評価確定

現行source08は`b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
通常hashはON。CPU48＋事前固定追加18でmono1倍n6全増加となり、性能一式は不採用。
Phase57分岐特殊化09、hash判定除去のON専用probe10も各9実行で改善を示さず棄却した。
05の時間・RTを08へ付け替えず、Interactive/AB/Paused深部/ABI等の広い08行列はNOT_RUN。
同一実行体による限定再利用は`results/performance_response/evidence/NATIVE08_REUSE_AUDIT.json`
の許可行だけ。現行08のcheckpointは保存済み独立RAWを検証して新規3case PASS。
[確定REPORT](../results/performance_response/REPORT.md)と同ディレクトリのSUMMARY/manifestを参照。
過去の計画・途中結果は残し、局所全体INCOMPLETE、公開WITHHELD、Merodoa既定UNCHANGEDを分ける。
