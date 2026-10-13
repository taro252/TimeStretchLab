"""Trace capture and OS analysis are separate from audio quality. No optimistic fallback."""
import csv
import json
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from phase43_trace_state import collect_states
try:
    from lxml import etree as ET
    LXML = True
except ImportError:
    from xml.etree import ElementTree as ET
    LXML = False

XCTRACE = ['/usr/bin/arch', '-arm64', '/usr/bin/xcrun', 'xctrace']


def export(trace, output, xpath=None):
    command = XCTRACE + ['export', '--input', str(trace), '--output', str(output)]
    command += ['--xpath', xpath] if xpath else ['--toc']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=240)
        log=result.stdout+result.stderr
        output.with_suffix(output.suffix + '.export.log').write_text(log)
        return result.returncode if '[Error]' not in log else 65
    except (OSError,subprocess.TimeoutExpired) as error:
        output.with_suffix(output.suffix + '.export.log').write_text(str(error))
        return 124


def capture_status(trace, record_exit, log, toc, toc_exit, audio_exit, pid):
    result = dict(TRACE_CAPTURE='FAIL', record_exit=record_exit, toc_exit=toc_exit,
                  trace_exists=trace.is_dir(), trace_bytes=0, record_errors=[], process_match=False)
    if trace.exists():
        result['trace_bytes'] = sum(p.stat().st_size for p in trace.rglob('*') if p.is_file())
    result['record_errors'] = [line for line in log.splitlines() if
        any(token in line.lower() for token in ('[error]', 'recording failed', 'cannot trace'))]
    try:
        tree = ET.parse(str(toc))
        processes = tree.findall('.//target/process')
        process = next(p for p in processes if p.get('pid') == str(pid))
        result['process_match'] = process.get('name') == 'phase43_play'
        result['target_exit'] = process.get('return-exit-status')
        result['thread_state_table'] = bool(tree.findall('.//table[@schema="thread-state"]'))
        # xctrace can return 54 when a launched/attached measured target failed.
        allowed_exit = record_exit == 0 or (record_exit == 54 and audio_exit != 0 and
            result['target_exit'] == str(audio_exit))
        result['record_exit_accepted'] = allowed_exit
        if (result['trace_bytes'] > 0 and toc_exit == 0 and result['process_match'] and
            result['thread_state_table'] and not result['record_errors'] and allowed_exit):
            result['TRACE_CAPTURE'] = 'PASS'
    except (OSError, StopIteration, ValueError, ET.ParseError):
        result['toc_error'] = 'invalid_or_missing_toc_or_target'
    return result


def target_row_count(xml, pid, tid):
    numbers, processes, threads = {}, {}, {}
    count = 0
    iterator = ET.iterparse(str(xml), events=('end',), tag='row') if LXML else ET.iterparse(str(xml),events=('end',))
    for _, row in iterator:
        if row.tag != 'row': continue
        for element in row.iter():
            if element.get('id') and element.text and element.text.strip().isdigit():
                numbers[element.get('id')] = int(element.text.strip())
        for element in row.iter('process'):
            if element.get('id'):
                cell=element.find('pid')
                if cell is not None: processes[element.get('id')] = numbers.get(cell.get('id') or cell.get('ref'))
        for element in row.iter('thread'):
            if element.get('id'):
                cell, owner = element.find('tid'), element.find('process')
                if cell is not None and owner is not None:
                    threads[element.get('id')] = (numbers.get(cell.get('id') or cell.get('ref')),
                        processes.get(owner.get('id') or owner.get('ref')))
        cells = list(row)
        if len(cells)>=4:
            identity = threads.get(cells[1].get('id') or cells[1].get('ref'))
            if identity == (tid,pid): count+=1
        row.clear()
        if LXML:
            while row.getprevious() is not None: del row.getparent()[0]
    return count


def coverage(intervals, first, last):
    totals=defaultdict(int)
    cursor=first
    # Clamp overlaps and do not count duplicate trace rows twice.
    for begin,end,state in sorted(intervals):
        begin=max(begin,first,cursor);end=min(end,last)
        if end>begin: totals[state]+=end-begin;cursor=end
        if cursor>=last: break
    length=max(1,last-first);covered=sum(totals.values())
    known=covered-totals['Unknown']
    return dict(coverage_fraction=covered/length,known_fraction=known/length,
                unrecorded_ns=max(0,length-covered),unknown_ns=totals['Unknown'],
                states_ns=dict(totals))


def analyze(toc, states, workers, pid, xml_exit=0):
    result=dict(TRACE_ANALYSIS='FAIL',xml_exit=xml_exit,worker_tid=None,target_rows=0)
    if xml_exit != 0: return result,[]
    try:
        tree=ET.parse(str(toc))
        start=tree.findtext('.//start-date')
        origin=int(datetime.fromisoformat(start).timestamp()*1e9)
        blocks=list(csv.DictReader(workers.open()))
        tid=int(blocks[0]['thread_id']);result['worker_tid']=tid
        result['target_rows']=target_row_count(states,pid,tid)
        intervals=collect_states(states,tid)
        result['thread_state_rows']=len(intervals)
        if not result['target_rows'] or not intervals: return result,[]
        lo,hi=min(i[0] for i in intervals),max(i[1] for i in intervals)
        joined=[]
        for b in blocks:
            first,last=int(b['start_unix_ns'])-origin,int(b['end_unix_ns'])-origin
            joined.append(dict(b,trace_start_ns=first,trace_end_ns=last,
                **coverage(intervals,first,last)))
        active=[j for j in joined if int(j['trace_start_ns'])>=lo and int(j['trace_end_ns'])<=hi]
        result['blocks_in_window']=len(active)
        result['trace_origin_unix_ns']=origin
        result['interval_start_ns']=lo;result['interval_end_ns']=hi
        result['known_fraction_in_window']=(sum((int(j['trace_end_ns'])-int(j['trace_start_ns']))*
            j['known_fraction'] for j in active)/max(1,sum(int(j['trace_end_ns'])-int(j['trace_start_ns']) for j in active)))
        result['TRACE_ANALYSIS']='PASS' if active else 'FAIL'
        # PASS means valid decoding/linkage, not that an Unknown interval has an identified cause.
        return result,joined
    except (OSError,ValueError,TypeError,IndexError,ET.ParseError):
        result['analysis_error']='missing_invalid_xml_or_worker_timing'
        return result,[]


def validate_run(path, record_exit, audio_exit, pid):
    trace=path/'system.trace';toc=path/'toc.xml';states=path/'states.xml'
    toc_exit=export(trace,toc) if trace.exists() else -1
    cap=capture_status(trace,record_exit,(path/'xctrace.log').read_text(),toc,toc_exit,audio_exit,pid)
    xml_exit=export(trace,states,'/trace-toc/run[@number="1"]/data/table[@schema="thread-state"]') if cap['TRACE_CAPTURE']=='PASS' else -1
    ana,joined=analyze(toc,states,path/'workers.csv',pid,xml_exit)
    (path/'trace_validation.json').write_text(json.dumps(dict(cap,**ana),indent=2))
    (path/'thread_join.json').write_text(json.dumps(joined,indent=2))
    return dict(cap,**ana)
