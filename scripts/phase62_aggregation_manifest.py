"""集計部分の置換候補。完全性を検査せず固定期待数を実施数へ転記しない。

PLAN.json: {"suites":[{"id":"...","mode":"strict_gates|legacy_gates|legacy_rows",
 "directory":"...", "pins":"..."}]}。旧rowsはID完全性だけを監査し、PCMを承認しない。
既存MANIFEST/結果には書かず、--outputで指定した新規ファイルだけを作る。
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from phase62_aggregation import (audit_legacy_gates, audit_legacy_rows, identity, read, strict_gates)


def entry(plan):
    folder=Path(plan['directory'])
    try:
        if plan['mode']=='strict_gates':
            certificate=strict_gates(folder)
        elif plan['mode']=='legacy_gates':
            certificate=audit_legacy_gates(folder,read(plan['pins']))
        elif plan['mode']=='legacy_rows':
            expected=read(folder/'EXPECTED.json');summary=read(folder/'SUMMARY.json')
            result=audit_legacy_rows(expected,summary)
            certificate=dict(result,status='INCOMPLETE',
                reason='legacy ID completeness only; per-case PCM/provenance adapter not supplied',
                measured_counts=dict(programs=result['executed']),
                source_inventory_sha256=expected.get('source',{}).get('sha256'))
        else:
            raise ValueError('unknown mode; weak rows-only fallback is forbidden')
        wanted=plan.get('expected_counts')
        if not isinstance(wanted,dict) or not wanted or wanted!=certificate.get('measured_counts'):
            raise ValueError('declared expected counts differ from measured child certificate')
        return dict(id=plan['id'],mode=plan['mode'],status=certificate['status'],
                    expected_counts=plan.get('expected_counts'),
                    measured_counts=certificate.get('measured_counts',{}),
                    audit=certificate,original_expected=identity(folder/'EXPECTED.json'),
                    original_summary=identity(folder/'SUMMARY.json'),local_overall_go=False)
    except (ValueError,OSError,KeyError,ET.ParseError) as error:
        return dict(id=plan['id'],status='INCOMPLETE',reason=str(error),measured_counts={},local_overall_go=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise RuntimeError('refusing an existing summary')
    plan=read(args.plan);ids=[x['id'] for x in plan['suites']]
    if not ids or len(ids)!=len(set(ids)):raise RuntimeError('missing/duplicate suite IDs')
    results=[entry(x) for x in plan['suites']]
    result=dict(schema=2,status='PASS' if all(x['status']=='PASS' for x in results) else 'INCOMPLETE',
                scope='aggregation evidence only',plan=identity(args.plan),suites=results,
                expected_suites=len(ids),executed_suites=len(results),local_overall_go=False,public_go=False)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],expected=len(ids),executed=len(results),local_overall_go=False)))
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
