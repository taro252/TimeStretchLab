"""checkpoint追加素材の失敗を旧5674と候補で診断する。assertは残し決定値だけ出力する。

旧testはHEADから読み、凍結旧archiveへlink。候補testは現在のfrozen sourceへlink。
製品src/testsは変更しない。対象testは任意素材の安全密度遷移を保証するものではないため、
元CTestのmix.wavと追加mono/stereoを別々に記録する。失敗はそのまま保存する。
"""
import argparse
from pathlib import Path
import shlex
import subprocess
import run_pairs as common
import build_frozen_client as frozen

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
old = common.load(BASE / 'frozen_clients_02/CLIENT.json')
new = common.load(BASE / 'build_final_01/BUILD.json')
common.require(old['baseline_commit'] == common.OLD_COMMIT and old['status'] == new['status'] == 'PASS', 'builds')
old_build = common.load(Path(old['baseline_build_record']['path']))
common.require(common.current_source_digest(ROOT) == new['source'], 'candidate source')
build = Path(new['binaries']['phase61_checkpoint_tests']['path']).parent
template = shlex.split((build / 'CMakeFiles/phase61_checkpoint_tests.dir/link.txt').read_text())
flags = frozen.flags_from_make(build / 'CMakeFiles/phase61_checkpoint_tests.dir/flags.make')
oi = [i for i, x in enumerate(template) if x.endswith('.o')]
oo = [i for i, x in enumerate(template) if x == '-o']
common.require(len(oi) == len(oo) == 1, 'link template')
originals = {'old': subprocess.check_output(['git', '-C', str(ROOT), 'show', common.OLD_COMMIT + ':tests/Phase61CheckpointTests.cpp']),
             'candidate': (ROOT / 'tests/Phase61CheckpointTests.cpp').read_bytes()}
record = {'status': 'INCOMPLETE', 'driver': common.identity(__file__), 'build': common.identity(BASE / 'build_final_01/BUILD.json'),
          'old_client': common.identity(BASE / 'frozen_clients_02/CLIENT.json'), 'source': new['source'], 'commands': [], 'clients': {}, 'rows': [],
          'scope': 'original assertions retained; normal-thread stderr decision facts only; no PCM/performance approval'}
for version, data in originals.items():
    folder = out / version
    folder.mkdir()
    original = folder / 'original.cpp'
    original.write_bytes(data)
    needle = 'require(old.change.plan.applied()'
    text = data.decode()
    common.require(text.count(needle) == 1, 'one diagnostic location')
    extra = 'std::cerr << "DIAG target " << target << " old_outcome " << int(old.change.plan.outcome) << " next_outcome " << int(next.change.plan.outcome) << " old_applied " << old.change.plan.applied() << " next_applied " << next.change.plan.applied() << " map_equal " << (oldPlanner.view()->map.starts()==newPlanner.view()->map.starts()) << "\\n"; '
    client = folder / 'client.cpp'
    client.write_text(text.replace(needle, extra + needle))
    root = Path(old_build['source_root']) if version == 'old' else ROOT
    obj, binary = folder / 'client.o', folder / 'checkpoint_diag'
    command = [template[0], '-I' + str(root / 'src'), *flags['CXX_FLAGS'], '-c', str(client), '-o', str(obj)]
    record['commands'].append(frozen.run(command, build, folder / 'compile.log'))
    link = template.copy()
    link[oi[0]], link[oo[0] + 1] = str(obj), str(binary)
    libs = []
    for i, token in enumerate(template):
        if token.endswith('.a'):
            item = old['link_inputs'][Path(token).name] if version == 'old' else common.identity(build / token)
            common.require(common.identity(item['path']) == item, 'library SHA')
            link[i] = item['path']
            libs.append(item)
    record['commands'].append(frozen.run(link, build, folder / 'link.log'))
    record['clients'][version] = {'binary': common.identity(binary), 'original': common.identity(original), 'diagnostic_source': common.identity(client), 'libraries': libs}
common.save(out / 'EXPECTED.json', {**record, 'fixtures': ['mix', 'mono48_16s', 'stereo441_16s'], 'expected_programs': 6})
for label, inp in (('mix', ROOT / 'results/phase31/input/mix.wav'),
                   ('mono48_16s', ROOT / 'build/progressive_adoption_20261023_01/inputs/mono48_16s.wav'),
                   ('stereo441_16s', ROOT / 'build/progressive_adoption_20261023_01/inputs/stereo441_16s.wav')):
    for version in ('old', 'candidate'):
        cmd = [record['clients'][version]['binary']['path'], str(inp)]
        log = out / (label + '_' + version + '.log')
        with log.open('w') as f:
            run = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=180)
        record['rows'].append({'id': label + '_' + version, 'command': cmd, 'returncode': run.returncode,
                               'input': common.identity(inp), 'log': common.identity(log), 'output': log.read_text()})
        common.save(out / 'SUMMARY.json', record)
        print(label, version, run.returncode, flush=True)
record.update(status='COMPLETE_OBSERVATIONS', complete=True)
common.save(out / 'SUMMARY.json', record)
