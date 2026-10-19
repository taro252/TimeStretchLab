"""全測定終了後の最終実測表。台帳のFAILと未実施を保持する。"""
import json,statistics
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';O=R/'results/phase62_fix';s=json.loads((O/'SUMMARY.json').read_text())
load=lambda p:json.loads(p.read_text())
lines=[]
def add(v=''):lines.append(v)
def table(headers,rows):
 add('| '+' | '.join(headers)+' |');add('|'+'|'.join('---' for _ in headers)+'|')
 for row in rows:add('| '+' | '.join(str(v).replace('|','／').replace('\n',' ') for v in row)+' |')
 add()
add('## 最終実測結果')
add('実機はApple M1 MacBookAir10,1・16GiB、最終ビルドはarm64。主行列の実出力は内蔵装置ID72・48kHz・512フレーム。入力レートの網羅と実装置レートの網羅を区別する。CTestの件数は実XML、以下の台帳件数は実際の期待ケースと終了結果から集計した。')
add()
table(['検証','結果','意味'],[
 ['Release／Debug CTest',f"{s['ctest']['release']['passed']}/{s['ctest']['release']['total']} ／ {s['ctest']['debug']['passed']}/{s['ctest']['debug']['total']}",'Phase59動的PCM、Phase60寿命、Phase61同期・seek・退役を含む既存回帰'],
 ['固定独立RAW','Exact896/896、Golden25/25','全ビット比較、非有限値は別に拒否'],
 ['有界RAW96','有限96/96＋再利用96/96','既存条件を維持'],
 ['全161速度×2方式','有限322/322＋再利用322/322','48kHz Stereo Float32。全入力形式の総当たりではない'],
 ['Release主行列','53条件・530周、機能／RAW／周期／実時間すべて通過','Clear後の診断も含む'],
 ['100ms実機','48条件×10周＋独立時計48件','6代表速度×4形式×2方式、最大callbackは別のオフライン行列でも照合'],
 ['長いA実機','12条件×100周','同一300秒素材、A=0/30/270秒、100/500ms、2倍、2方式'],
 ['長期実機','100周／1000周、Release／Debugとも通過','1000周を4100境界オフラインで代替しない'],
 ['基本長区間','2秒の.4/1/2倍、10秒／30秒の2倍','実機5条件、各4周。全曲は主行列にも含む'],
 ['オフライン境界','8形式×24条件＋4100境界','callback64/128/512/4096、有限履歴。実時間の承認ではない'],
 ['品質キャプチャ',f"{s['quality']['passed']}/{s['quality']['cases_measured']}、RAW／加工数式／finite一致",'176条件の入力A/B・レートも一致。主観音質の承認ではない'],
 ['既存実曲ピアノ',f"{s['piano_quality']['passed']}/{s['piano_quality']['measured']}",'30秒48kHz Stereo Float32の既存素材。楽器の収録方法は独立未確認'],
 ['Pause／供給不足','実renderの末尾1／64フレーム競合、512要求100受領412padding等を通過','製品callbackに待機やテストバリアを追加しない']])
add('### 全スイートの台帳')
add('PASSはそのケースに宣言した検査の成功であり、音質・公開・時計異常0など全ゲートの一括承認ではない。たとえば時計再計算のPASSは、記録と独立再計算の一致を示す。')
add()
add('最終F9実行ドライバーは20件中PASS13／FAIL2／NOT_RUN5／INCOMPLETE0。F8で完了した7件は別の元ソース台帳を保ち、依存関係と実行体不変の監査で適用した。ドライバーの状態は子スイート全体の状態であり、機能とRTは下位の別ゲートで確認する。')
add()
table(['F9ドライバー全件','状態','未実施理由／失敗理由'],[[r['id'],r['status'],'; '.join(r.get('reasons',[]))] for r in s['final_driver']['cases']])
table(['主スイート','PASS','FAIL','NOT_RUN','INCOMPLETE'],[[n,*[v['counts'][k] for k in ('PASS','FAIL','NOT_RUN','INCOMPLETE')]] for n,v in sorted(s['suites'].items())])
table(['追加スイート','PASS','FAIL','NOT_RUN','INCOMPLETE'],[[n,*[v['counts'][k] for k in ('PASS','FAIL','NOT_RUN','INCOMPLETE')]] for n,v in s['extra_evidence'].items()])
add('`waveform_analysis`／`piano_waveform`／`boundary_methods` の元の図生成失敗は、描画用matplotlibが未導入だったためで、元の失敗台帳を保持した。数値176／16／192条件を成功として残し、図だけを専用依存フォルダと新しい `figure_repair` 台帳で再生成した。音声試験や失敗したRT試験を再実行して成功へ置き換えていない。')
add()
add('### 再利用、初回準備、CPUとメモリ')
add('旧版と新版の制御した直列1000周比較は、同一入力SHA `7ec3f2aa3c2e746643d24cfbda653bdde6eaedc9dd82be6a9ca7159372fe26ce`、A=17/B=24017、2倍、Candidate、Release arm64、装置ID72・48kHz・512で行った。旧版は約152.75秒で「次周期PCM不足またはcallback上限超過」により安全停止し、結果JSONを生成しなかった。新版は1000周を完走した。双方の装置設定は前後一致したが、旧版の完走CPU値がないため、制御した比較のCPU改善率は算出できない。診断文だけでは不足と上限超過のどちらか、またスケジューラ等の根因までは特定できない。')
add()
a=s['comparison_1000']['old'];b=s['comparison_1000']['new'];c=load(F/'paired_1000/new/result.json')
table(['走行','CPU秒','経過秒','CPU使用率','準備回数','周期契約'],[[name,f"{v['process_cpu_s']:.6f}",f"{v['wall_s']:.6f}",f"{v['process_cpu_s']/v['wall_s']*100:.3f}%",v['preparations'],contract] for name,v,contract in [('旧・初回保存の成功1000周',a,'L−N'),('新・最終主試験1000周',b,'L'),('新・制御した直列比較1000周',c,'L')]])
add('各走行n=1。旧・初回保存の成功は同じ記録上の入力・範囲・速度・rate/bufferだが、装置IDの前後トレースがないため厳密な対照走行とは区別する。CPU使用率は全プロセスCPU秒÷経過秒×100（1コア=100%）。通常増分再生CPUと旧版の段階別CPUは未測定であり、差のすべてを再合成削減へ因果帰属しない。')
add()
add(f"新版主1000周はMap構築{b['map_builds']}、worker生成{b['workers_created']}、準備{b['preparations']}、warm FFT plan生成{b['warm_fft_plans']}、warm prefix破棄{b['warm_discarded_frames']}。cold prefix CPU {b['cold_prefix_cpu_s']:.6f}秒、初回DSP CPU {b['cold_dsp_cpu_s']:.6f}秒、warm生成・コピー・FIFO書込み合計CPU {b['warm_work_cpu_s']:.6f}秒。warmは先読み分を含む処理合計で、各周のcallback時間ではない。RSSは{b['rss_start']:,}→{b['rss_end']:,}バイト、観測peak {b['peak_rss']:,}バイト。")
d=s['comparison_1000']['new_100_cycle_interval_cpu_percent']
add(f"100周間隔10区間のCPU使用率は平均{d['mean']:.3f}%、中央値{d['median']:.3f}%、p95 {d['p95']:.3f}%、最大{d['max']:.3f}%。これは1周ごとの分布ではない。全プロセスのスレッド観測値は{s['comparison_1000']['new_thread_samples']}で周回に比例した増加は見られない。DSP生成カウンタの2と、OS／試験スレッドを含む総数を区別する。")
add()
rows=[]
for p in sorted((F/'evidence/release_longA').glob('*/result.json')):
 v=load(p);rows.append([p.parent.name,f"{v['ready_ms']:.3f}",f"{v['cold_prefix_cpu_s']:.6f}",f"{v['warm_work_cpu_s']:.6f}",v['reuse_count'],v['warm_discarded_frames']])
table(['A／区間／方式（2倍）','初回Ready ms','cold prefix CPU秒','warm合計CPU秒','準備済み再利用周期数','warm prefix破棄'],rows)
add('全12条件で準備1、Map1、worker2。coldはAが後半ほど長く、A270秒のReadyは約30秒であり200ms以内を約束しない。warmはA以前の全prefix再合成を繰り返さず、部分ブロック上限内の復元か短区間RAWコピーを使う。再利用周期数は有限FIFOの先読みを含み、可聴周回100とは異なる。長いAの10秒区間は短区間RAW上限を超える条件でも独立RAWとB継続を照合した。')
add()
add('### 時計とDebugの残る失敗')
add('最終固定Release主行列・長期・短区間・長いA・Clear後の診断ではDSP／callback期限、host／sample診断、HAL窓、不足／padding、Workgroup、callback確保／解放は0。故障注入の意図した停止はこの正常系0判定へ混ぜない。')
add()
for name,value in s['extended_startups'].items():add(f"- {name}: fresh start {value['completed']}/{value['expected']}、host={value['host_errors']}、sample={value['sample_errors']}、callback期限={value['callback_deadlines']}、DSP期限={value['worker_deadlines']}。")
add()
add('装置の物理レートは各試験後に元の48kHzへ復元した。旧異常と途中F5の48→48異常は保持し、独立再計算でもcadence／sample各1。F5の最初の2callbackではsource sampleTimeが0→1120、要求512に対して余分608フレーム、host差23.333ms。rawは連続し、render／clock epochは不変、論理出力1024<確定周期11877で最初のBより前だった。SRCだけが原因と断定できない。末尾履歴に最初に残った境界を真の初回Bとは呼ばない。追加300回が0でも旧異常の根本原因は未解決である。')
add()
add('Debug主行列は53条件すべて機能／RAW／周期通過、RTは48条件通過・5条件失敗。DSP期限超過は48kHz Stereo PCM16 Baseline2倍1、music1秒1、music2秒1、music10秒21、全曲10で最終累積34件。操作試験では同Stereo PCM16のCandidate／Baseline各1で2件。Clear前の値を最終累積へ二重加算しない。host／sample、callback期限、不足／padding等は0。Debug長期100／1000周は別に通過したが、この失敗を取り消さない。旧x86_64 Debug全曲121件も別の履歴である。')
add()
add('### 音量、位相、アタックと比較資料')
add('固定RAW、窓外、独立数式の一致と、音楽的な良さを分離する。各品質ケースの10／25／100msは検証済み定常周期を前後へ延長した窓であり、短い周期の物理録音ではない。出力ゲインは0.5。')
add()
table(['窓','RMS変化最小 dB','最大 dB','数値チャンネル窓数'],[[ms,f"{v['min']:.6f}",f"{v['max']:.6f}",v['n']] for ms,v in s['quality']['rms_change_db'].items()])
add(f"ピークはゲイン0.5適用後{s['quality']['peak_gain05']:.9f}、意図しない0フレーム{s['quality']['unexpected_zero_frames']}。最大+13.138103dBは100ms・0.40倍のimpulse_train両方式で、10ms窓のRAW RMS約0.00717588→加工後約0.03256718。周期維持の補正が局所エネルギーを増すため、無音量変化を保証できない。旧−5.548〜+1.084dBとは数式・評価窓が違い、直接の改善値にしない。")
add()
add('1秒文脈のFFTは1Hz間隔で、20–200／200–4000／4000–Nyquist帯域、55Hz／437.3Hzの左右位相、左右RMS・相関、境界差分・傾き、20msの局所差分を保存した。短い5ms FFTだけで低音を承認していない。192条件で、現行補正と周期Lを保ち両端を0にするスカラー減衰案を比較した。減衰案は2つの既存端点を意図して0へ加工するもので、追加無音ではないがアタック・音量低下の危険があり、製品には未実装。比較の技術PASSを採用承認としない。')
add()
method_rows=[]
for key in ('impulse_train_100ms_400000_candidate','bass_long_1000000_baseline','low_sustain_long_400000_candidate','stereo_phase_100ms_2000000_candidate','drums_long_2000000_candidate','piano_real_long_2000000_candidate'):
 v=load(F/'boundary_methods'/(key+'.json'));w={r['milliseconds']:r for r in v['windows']}
 method_rows.append([key,*[f"{w[ms][method]['change_db'][0]:.3f}" for ms in (10,100) for method in ('current','zero_taper_proposal')]])
table(['素材・速度・方式','10ms現行 dB','10ms減衰案 dB','100ms現行 dB','100ms減衰案 dB'],method_rows)
add('上表は左チャンネルのRAW比。減衰案は現行の増幅を抑える一方、局所音量を下げる。RMS差だけでクリック、位相、アタック、定位を承認せず、採用判断は別に行う。')
add()
add('試聴用には44条件のRAW／現行加工、実曲ピアノ4条件、方式比較6条件のRAW／現行／減衰案を、それぞれ同ゲイン0.5・最低10秒で保存した。短区間はビット照合済み定常周期の反復。注目点は低音の脈動、左右定位、インパルス／打楽器／ピアノのアタック、境界の音量、拍の周期。実際の試聴と音響ループバックは未実施。')
add()
add('比較図は `build/phase62_fix/run_01/final_v9/figure_repair/{waveform_analysis,piano_waveform,boundary_methods}/`、WAVと全数値は元の各スイートにある。描画依存のバージョンはPLOT_DEPENDENCIES.jsonに記録する。')
add()
add('### Sandboxと寿命の範囲')
add('実際に署名したTimeStretchLab専用App SandboxでNSOpenPanelから1つの入力WAVと専用出力フォルダだけを選択し、選択入力をscope中に一度デコード、100ms100周×2方式と13故障処理を実行した。全所有者停止後にscopeを終了し、許可外パスが実際に拒否されることを確認した。別の非Sandbox試験では2所有者が入力親の破棄後も参照を保持し、両方式1000周期後もFD2、最後の所有者破棄後FD0を確認した。非SandboxのFD結果をMerodoaのTCC／bookmarkの代替にしない。')
add()
add('## 9ゲートとStep3')
table(['番号／ゲート','判断','成立範囲と未達'],[[str(g['id'])+' '+g['name'],g['verdict'],g.get('scope','')+'。'+g.get('reason','')] for g in s['gates']])
add('Merodoa Step3は専用直列キュー、値だけのsnapshot、scope寿命、理由付き拒否、診断表示を確認する明示opt-in研究ブリッジと、上記の固定速度・検証済み位置／形式／装置条件まで進められる。Merodoa本体はこの依頼では変更していない。一般公開、200ms監視の既定置換、Capabilities.seekの有効化は進めない。`allowExperimentalLoops=false`、`publicLoopApproved=false`、`Capabilities.seek=false`を維持する。')
add()
add('次はPHASE62_FIX_LOOP_REUSE.md末尾の生成フロンティア引継ぎを実装し、Phase59同一要求・適用履歴の動的独立参照、L1/L2、動的MapのBと次周期を最大2DSPで照合する。異速度境界の独立キャプチャ、B直前手動seek一般化、時計異常の起動経路調査、Debugの処理期限調整、試聴／物理録音、実アプリTCC拒否／stale bookmarkはそれぞれ別の未達項目として残す。')
add()
add('最終の容量／Git／旧証拠／Merodoa不変更の検査はFINAL_CHECKS.json、全変更ファイルとSHAはCHANGED_FILES.json、全大容量原本のSHA索引はARTIFACT_MANIFEST.jsonから辿れる。ステージ済み検査と、全未ステージ追跡ファイル・未追跡候補の50,000,000バイト境界検査を分ける。コミット・Pushはこの依頼に含めず実施しない。')
p=O/'REPORT.md';text=p.read_text().split('<!-- FINAL_MEASURED_TABLES -->')[0].rstrip();p.write_text(text+'\n\n<!-- FINAL_MEASURED_TABLES -->\n\n'+'\n'.join(lines)+'\n')
print('REPORT',p.stat().st_size)
