"""Strict saved-evidence validation. Row counts come from stopped in-memory capture."""
import csv
import hashlib
import json
import re
from pathlib import Path

REQUIRED={
 'callbacks.csv':{'sequence','epoch','timestamp_flags','sample_time','callback_start_mach_ns','callback_end_mach_ns','io_complete_mach_ns','early_end_mach_ns','host_mach_ns','render_requested_frames','wanted','received'},
 'workers.csv':{'cycle_sequence','output_start','publication_frames','start_mach_ns','published_mach_ns','cycle_wall_s','cycle_cpu_s'},
 'replay.csv':{'generation','from','target','applied_frame','applied_output','completion_output'},
 'workers.csv.guard.csv':{'generation','safe','guard_wall_s','guard_cpu_s'},
}


def read_csv(path,required):
    data=path.read_bytes()
    if not data or not data.endswith(b'\n'):raise ValueError('missing_header_or_truncated_final_line')
    text=data.decode('utf-8')
    import io
    reader=csv.DictReader(io.StringIO(text),strict=True)
    header=reader.fieldnames or []
    if len(set(header))!=len(header) or not required.issubset(header):raise ValueError('required_header_missing_or_duplicate')
    rows=list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):raise ValueError('partial_or_extra_columns')
    return rows,hashlib.sha256(data).hexdigest()


def validate(path,values,log_text='',legacy=False):
    path=Path(path);faults=[];tables={};files={}
    for name,columns in REQUIRED.items():
        expected_cols=set(columns)
        if legacy and name=='workers.csv':expected_cols.discard('cycle_sequence')
        if legacy and name=='callbacks.csv':expected_cols.difference_update({'io_complete_mach_ns','early_end_mach_ns'})
        try:
            rows,digest=read_csv(path/name,expected_cols);tables[name]=rows
            files[name]=dict(rows=len(rows),sha256=digest,required_columns=sorted(expected_cols))
        except (OSError,ValueError,UnicodeError,csv.Error) as error:
            faults.append(f'{name}:{error}')
    try:
        cb=tables.get('callbacks.csv',[]);workers=tables.get('workers.csv',[])
        if len(cb)!=int(values['callback_records_retained']):faults.append('callback_row_count')
        total=int(values.get('callback_records_total',int(values['callback_records_retained'])+int(values['callback_records_evicted'])))
        expected=list(range(total-len(cb)+1,total+1))
        if [int(r['sequence']) for r in cb]!=expected:faults.append('callback_sequence_range_or_gap')
        if total!=int(values['callback_records_retained'])+int(values['callback_records_evicted']):faults.append('callback_drop_accounting')
        if not legacy:
            retained=int(values['worker_records_retained']);worker_total=int(values['worker_records_total'])
            if len(workers)!=retained:faults.append('worker_row_count')
            if [int(r['cycle_sequence']) for r in workers]!=list(range(1,retained+1)):faults.append('worker_sequence_range_or_gap')
            if worker_total!=retained+int(values['worker_profile_records_dropped']):faults.append('worker_drop_accounting')
            if len(tables.get('replay.csv',[]))!=int(values['replay_records_expected']):faults.append('replay_row_count')
            if len(tables.get('workers.csv.guard.csv',[]))!=int(values['guard_records_expected']):faults.append('guard_row_count')
            if values.get('diagnostic_csv_save_ok')!='1':faults.append('native_csv_io_failed_or_unmeasured')
        generations=[int(m.group(1)) for m in re.finditer(r'^change=\d+ generation=(\d+) ',log_text,re.M)]
        got=[int(r['generation']) for r in tables.get('replay.csv',[])]
        if got!=generations:faults.append('replay_plan_generation_mismatch')
        if got!=sorted(set(got)):faults.append('replay_generation_duplicate_or_order')
    except (KeyError,ValueError,TypeError):faults.append('capture_counts_missing_or_invalid')
    result=dict(CSV_INTEGRITY='FAIL' if faults else 'PASS',faults=faults,files=files,legacy=legacy)
    return result,tables
