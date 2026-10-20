"""実出力LoopのRAW prefixを、固定した旧Phase59 planner/DSPで独立照合する。"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import time

from phase59_native_validation import wav_info
from phase62_evidence import identity, sha

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SHA = '1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818'
REFERENCE_BASE = 'bb22efcbd27f999e8ffe85bbe3f03e20895be3f2'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def require(value, reason):
    if not value:
        raise ValueError(reason)


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def finite_file(path):
    samples = 0
    with path.open('rb') as stream:
        while block := stream.read(1 << 20):
            require(len(block) % 4 == 0, 'Float32 RAWのバイト数が4の倍数ではない')
            for value, in struct.iter_unpack('<f', block):
                require(math.isfinite(value), '参照RAWにNaN/Infがある: sample='+str(samples))
                samples += 1
    return samples


def compare_prefix(actual, reference, frames, channels, mismatch):
    expected_bytes = frames*channels*4
    require(actual.stat().st_size == expected_bytes, 'NATIVE.captured_framesとRAWサイズが一致しない')
    require(reference.stat().st_size >= expected_bytes, '独立参照が実出力prefixより短い')
    digest = hashlib.sha256()
    done = 0
    with actual.open('rb') as left, reference.open('rb') as right:
        while block := left.read(1 << 20):
            wanted = right.read(len(block))
            require(len(wanted) == len(block), '独立参照prefixの途中欠落')
            for index, (a, b) in enumerate(zip(struct.iter_unpack('<f', block), struct.iter_unpack('<f', wanted))):
                sample = done//4+index
                if not math.isfinite(a[0]) or not math.isfinite(b[0]):
                    failure = dict(status='FAIL', reason='NaN/Inf', frame=sample//channels, channel=sample % channels)
                    write(mismatch, failure)
                    raise ValueError('実出力または独立参照prefixにNaN/Inf')
            if block != wanted:
                for index in range(0, len(block), 4):
                    if block[index:index+4] != wanted[index:index+4]:
                        sample = (done+index)//4
                        failure = dict(status='FAIL', reason='Float32生ビット不一致', frame=sample//channels,
                            channel=sample % channels, actual_bits=struct.unpack_from('<I', block, index)[0],
                            reference_bits=struct.unpack_from('<I', wanted, index)[0])
                        write(mismatch, failure)
                        raise ValueError('実出力RAW prefixと旧独立DSPが不一致')
                raise ValueError('実出力RAW prefixの長さ不一致')
            digest.update(block)
            done += len(block)
    require(done == expected_bytes and frames > 0, 'RAW比較が0件または途中終了')
    return dict(frames=frames, channels=channels, bytes=done, channel_order='frame-major interleaved',
                bit_exact=True, nonfinite=0, prefix_sha256=digest.hexdigest())


def map_position(nodes_path, input_frame):
    data = nodes_path.read_bytes()
    require(len(data) >= 16 and len(data) % 8 == 0, '旧Map node列が欠落または不正')
    nodes = [node for node, in struct.iter_unpack('<q', data)]
    require(all(a <= b for a, b in zip(nodes, nodes[1:])), '独立Mapが単調ではない')
    require(input_frame >= 0 and input_frame <= (len(nodes)-1)*1024, '入力Bが独立Mapの確定範囲外')
    # TimeMap::outputPositionForInputSampleと同じ1024 hop線形補間。
    # 正の出力なのでstd::llround（中間を0から離す丸め）はfloor(x+0.5)。
    fractional = float(input_frame)/1024.0
    left = min(int(fractional), len(nodes)-2)
    local = fractional-left
    exact = float(nodes[left])+local*float(nodes[left+1]-nodes[left])
    require(math.isfinite(exact) and exact >= 0, '独立Map(B)が非有限または負')
    return dict(source_hop=1024, input_B=input_frame, left_node=left, fractional_local=local,
                interpolated_output=exact, rounded_output=math.floor(exact+0.5), nodes=len(nodes),
                rounding='positive std::llround: floor(value+0.5)')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('preset', choices=('candidate', 'baseline'))
    parser.add_argument('export', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--native-binary', type=Path,
                        help='実行に使用したnative probe。NATIVEにhashがなければ監査時点の実体として記録する')
    parser.add_argument('--timeout', type=float, default=1800.)
    args = parser.parse_args()
    input_path, exported, reference = (path.resolve() for path in (args.input, args.export, args.reference))
    require(exported.is_dir(), 'native exportディレクトリがない')
    require(exported.is_relative_to(ROOT/'build'), '大容量PCMのaudit出力先はGit管理外のbuild/以下にする')
    require(math.isfinite(args.timeout) and args.timeout > 0, 'timeoutは正の有限秒数を指定する')
    audit = exported/'audit'
    require(not audit.exists(), 'audit/は新規必須。既存証拠の再利用・上書きは禁止')
    audit.mkdir()
    command = [str(reference), str(input_path), '1000000', args.preset, str(exported),
               str(audit/'reference.f32'), str(audit/'reference')]
    summary = dict(suite='phase62_dynamic_native_audit', expected=1, executed=0, status='INCOMPLETE',
                   initial_micros=1000000, preset=args.preset, source='native old-loop session RAW prefix 0:C',
                   independent_planner=False, independent_DSP_RAW=False, local_overall_go=False, public_go=False,
                   mixer_final_output='NOT_RUN', next_fixed_cycle='NOT_RUN', physical_loopback='NOT_RUN',
                   subjective_listening='NOT_RUN', callback_allocation_probe='NOT_RUN', deadline_approval='NOT_RUN')
    write(audit/'EXPECTED.json', dict(schema=1, expected=1, command=command, reference_expected_sha256=REFERENCE_SHA,
        baseline=REFERENCE_BASE, required_native_files=['NATIVE.json', 'actual.f32', 'speeds.csv', 'plans.csv', 'plan_frontiers.csv'],
        assertions=['current_cycle_observed=true', 'raw_errors=0', 'completion_output<captured_frames',
                    'frozen frontiers_exact=true and plans=1', 'all captured Float32 bits/channels/frames equal prefix',
                    'finite actual/reference', 'independent linear Map(input_B)==NATIVE.dynamic_B'],
        limitations={key: value for key, value in summary.items() if value == 'NOT_RUN'}))
    write(audit/'SUMMARY.json', summary)
    invocation = dict(command=command, status='NOT_RUN', expected_exit=0)
    write(audit/'COMMANDS.json', [invocation])
    try:
        source_files = [exported/name for name in ('NATIVE.json', 'actual.f32', 'speeds.csv', 'plans.csv', 'plan_frontiers.csv')]
        frozen_inputs = {str(path): identity(path) for path in [input_path, *source_files]}
        reference_identity = identity(reference)
        manifest_path = ROOT/'results/phase59/CAPTURED_REFERENCE.json'
        manifest = json.loads(manifest_path.read_text())
        frozen_manifest_path = ROOT/'results/phase59/FROZEN_REFERENCE.json'
        frozen_manifest = json.loads(frozen_manifest_path.read_text())
        require(reference_identity['sha256'] == manifest.get('binary_sha256') == REFERENCE_SHA,
                '旧captured_referenceの実体SHAが固定manifestと一致しない')
        require(manifest.get('baseline_head') == frozen_manifest.get('baseline_head') == REFERENCE_BASE and
                manifest.get('library_sha256') == frozen_manifest.get('library_sha256'), '独立参照の基準・ライブラリ系譜が異なる')
        driver = ROOT/'results/phase59/reference_driver_sources/Phase59CapturedReference.cpp'
        require(sha(driver) == manifest.get('driver_source_sha256'), '保存した旧再現器ソースSHAが異なる')
        native = json.loads((exported/'NATIVE.json').read_text())
        info = wav_info(input_path)
        frames, channels = native['captured_frames'], native['channels']
        require(isinstance(frames, int) and frames > 0 and channels in (1, 2), 'nativeフレーム数・チャンネル数が不正')
        require(native['current_cycle_observed'] is True and native['raw_errors'] == 0, '現在周期適用またはRAW連続性を観測していない')
        require(channels == info['channels'] and native['source_rate'] == info['rate'], 'native RAWと入力の形式が異なる')
        require(0 < native['input_B'] <= info['frames'] and native['dynamic_B'] > frames, '可聴prefixが現在周期Bの内側ではない')
        applied = [row for row in rows(exported/'speeds.csv') if float(row['applied_s']) >= 0]
        plans = rows(exported/'plans.csv')
        require(len(applied) == len(plans) == 1, '独立監査は実Applied 1件のnative probeを要求する')
        operation = applied[0]
        completion = int(operation['completion_output'])
        require(int(operation['target_micros']) == 750000 and float(operation['completed_s']) >= 0 and
                0 < int(operation['applied_output']) <= completion < frames, '変更PCMの完了位置まで実出力で観測していない')
        native_binary = None
        binary_scope = 'NOT_RUN: NATIVEに実行体SHAが無く、--native-binaryも未指定'
        supplied_binary = args.native_binary or (Path(native['binary_path']) if native.get('binary_path') else None)
        if supplied_binary:
            native_binary = identity(supplied_binary)
            if native.get('binary_sha256'):
                require(native_binary['sha256'] == native['binary_sha256'], 'native実行体SHAがexport時と異なる')
                binary_scope = 'NATIVEに記録した実行体SHAと監査時の実体が一致'
            else:
                binary_scope = '呼出側が指定した実行体の監査時SHA。export時の同一性はNATIVE単独では未記録'
        provenance = dict(auditor=identity(__file__), python=identity(Path(sys.executable)), input=frozen_inputs[str(input_path)],
            native_artifacts=list(frozen_inputs.values())[1:], native_binary=native_binary, native_binary_identity_scope=binary_scope,
            reference=reference_identity, reference_manifest=identity(manifest_path), frozen_manifest=identity(frozen_manifest_path),
            frozen_driver=identity(driver), native=native, command=command)
        write(audit/'PROVENANCE.json', provenance)
        invocation.update(status='INCOMPLETE', started_ns=time.time_ns(), executable=reference_identity)
        write(audit/'COMMANDS.json', [invocation])
        started = time.monotonic()
        try:
            with (audit/'reference.log').open('x') as log:
                process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
            invocation.update(exit=process.returncode, status='PASS' if process.returncode == 0 else 'FAIL')
        except subprocess.TimeoutExpired:
            invocation.update(exit=-1, status='INCOMPLETE', timeout=True)
        finally:
            invocation.update(wall_s=time.monotonic()-started)
            write(audit/'COMMANDS.json', [invocation])
        require(invocation.get('exit') == 0, '旧独立planner/DSPの実行失敗またはtimeout')
        frozen = json.loads((audit/'reference.json').read_text())
        require(frozen.get('frontiers_exact') is True and frozen.get('plans') == 1, '実測Frontier・旧planner計画の最終統計が一致しない')
        require(frozen['channels'] == channels and frozen['frames'] >= frames, '独立参照のチャンネル・全出力長が不正')
        reference_raw = audit/'reference.f32'
        require(reference_raw.stat().st_size == frozen['frames']*channels*4 and sha(reference_raw) == frozen['pcm_sha256'], '独立RAWの全長・SHAが最終統計と異なる')
        require(sha(audit/'reference.nodes.bin') == frozen['map_sha256'], '独立Map SHAが最終統計と異なる')
        reference_plans = rows(audit/'reference.plans.csv')
        require(len(reference_plans) == 1 and int(reference_plans[0]['completion_output']) == completion and
                int(reference_plans[0]['applied_output']) == int(operation['applied_output']), '独立適用/完了座標がnative要求と異なる')
        comparison = compare_prefix(exported/'actual.f32', reference_raw, frames, channels, audit/'FIRST_MISMATCH.json')
        reference_samples = finite_file(reference_raw)
        position = map_position(audit/'reference.nodes.bin', native['input_B'])
        require(position['rounded_output'] == native['dynamic_B'], 'NATIVE.dynamic_Bと独立動的Map(B)が異なる')
        for path, expected in frozen_inputs.items():
            require(sha(path) == expected['sha256'], '監査中に入力またはnative証拠が変更された: '+path)
        require(sha(reference) == REFERENCE_SHA, '監査中に旧参照実行体が変更された')
        summary.update(status='PASS', executed=1, independent_planner=True, independent_DSP_RAW=True,
            frontiers_exact=True, plans=1, current_cycle_observed=True, raw_errors=0, completion_output=completion,
            captured_frames=frames, channels=channels, comparison=comparison, reference_samples_finite=reference_samples,
            dynamic_B=position, native_dynamic_B=native['dynamic_B'], map_version=native['map_version'],
            reference_exit=invocation['exit'], input_sha256=frozen_inputs[str(input_path)]['sha256'],
            native_binary=native_binary, native_binary_identity_scope=binary_scope,
            reference_sha256=REFERENCE_SHA, reference_pcm_sha256=frozen['pcm_sha256'], reference_map_sha256=frozen['map_sha256'])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        summary.update(status='INCOMPLETE' if invocation.get('timeout') else 'FAIL', reason=str(error), reference_exit=invocation.get('exit'))
    finally:
        write(audit/'SUMMARY.json', summary)
        write(audit/'ARTIFACTS.json', [identity(path) for path in sorted(audit.iterdir()) if path.is_file() and path.name != 'ARTIFACTS.json'])
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
