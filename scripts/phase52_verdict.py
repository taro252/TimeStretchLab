"""Strict developer-player verdict; expected route stops are never normal EOS."""
import math,re
NUMERIC=('output_frames','produced_frames','consumed_frames','presented_frames','missing_frames','underrun_calls','max_continuous_missing','rejected_writes','callback_allocations_measured','callback_cpp_allocations','callback_overruns','host_missing','host_backwards','host_cadence_errors','sample_errors','hal_window_misses','records_dropped','sample_rate')
def classify(row,exit_code,expected_route=False,remaining_actions=0):
 """Native counters only; finalize() owns the complete PCM/CSV/session verdict."""
 errors=[];v={}
 for k in NUMERIC:
  try:
   x=float(row[k]);assert math.isfinite(x) and x>=0
   v[k]=x
  except (KeyError,TypeError,ValueError,AssertionError):errors.append(k)
 if not re.fullmatch('[a-f0-9]{64}',str(row.get('raw_pcm_sha256',''))):errors.append('raw_pcm_sha256')
 if errors:return dict(AUDIO_QUALITY='FAIL' if v.get('missing_frames',0)>0 else 'INDETERMINATE',MEASUREMENT_QUALITY='FAIL',VERDICT='FAIL',errors=errors)
 supply=any(v[k]>0 for k in ('missing_frames','underrun_calls','rejected_writes','callback_overruns','callback_cpp_allocations'))
 normal=row.get('state')=='Ended' and row.get('reason')=='EOS' and row.get('eos')=='1' and v['consumed_frames']==v['output_frames'] and v['presented_frames']==v['consumed_frames']
 route=expected_route and row.get('state')=='Stopped' and row.get('reason')=='RouteChanged' and row.get('eos')=='0' and row.get('route_stopped')=='1'
 audio='PASS' if not supply and (normal or route) and remaining_actions==0 else 'FAIL'
 measure='PASS' if not any(v[k]>0 for k in ('host_missing','host_backwards','host_cadence_errors','sample_errors','hal_window_misses','records_dropped')) and v['callback_allocations_measured']==1 and v['sample_rate']>0 else 'FAIL'
 # Preserve the originating verdict. Never silently upgrade a saved FAIL.
 if row.get('AUDIO_QUALITY')!='PASS':audio='FAIL'
 if row.get('MEASUREMENT_QUALITY')!='PASS':measure='FAIL'
 return dict(AUDIO_QUALITY=audio,MEASUREMENT_QUALITY=measure,VERDICT='PASS' if audio==measure=='PASS' and exit_code==0 else 'FAIL',errors=errors)

def finalize(row, exit_code, sessions, evidence, expected_route=False, expected_stop=False,
             remaining_actions=0, pcm_correction=None):
 """One final gate for normal verification and explicitly bounded PCM corrections."""
 result=dict(row)
 original=dict(row)
 if expected_stop:
  # A deliberate user stop is a terminal session, never EOS.
  check=dict(row,state='Stopped',reason='RouteChanged',eos='0',route_stopped='1')
  verdict=classify(check,exit_code,True,remaining_actions)
  if row.get('state')!='Stopped' or row.get('reason')!='User' or str(row.get('eos'))!='0':
   verdict['AUDIO_QUALITY']='FAIL'
 else: verdict=classify(row,exit_code,expected_route,remaining_actions)
 result.update(verdict)
 try: concurrent=float(row.get('concurrent_renders',0)); invalid_concurrent=not math.isfinite(concurrent) or concurrent!=0
 except (TypeError,ValueError): invalid_concurrent=True
 if row.get('worker_error') or row.get('native_error') or invalid_concurrent:
  result['AUDIO_QUALITY']='FAIL'
 result['CSV_INTEGRITY']=evidence.get('CSV_INTEGRITY','FAIL')
 result['evidence']=evidence
 if original.get('CSV_INTEGRITY')=='FAIL':result['CSV_INTEGRITY']='FAIL'
 if result['CSV_INTEGRITY']!='PASS':result['MEASUREMENT_QUALITY']='FAIL'
 if pcm_correction:
  if not pcm_correction.get('reason') or not pcm_correction.get('before') or not pcm_correction.get('after'):
   result['PCM_CORRECTNESS']='FAIL'
  else:
   result['PCM_CORRECTNESS']=pcm_correction['after'].get('PCM_CORRECTNESS','FAIL')
   result['pcm_correction']=pcm_correction
 # Only PCM_CORRECTNESS may be corrected; originating AUDIO/MEASUREMENT FAIL are sticky.
 result['sessions']=sessions
 if not sessions: result['SESSION_INTEGRITY']='INDETERMINATE'
 elif any(s.get('VERDICT')=='FAIL' for s in sessions):result['SESSION_INTEGRITY']='FAIL'
 elif all(s.get('VERDICT')=='PASS' for s in sessions):result['SESSION_INTEGRITY']='PASS'
 else:result['SESSION_INTEGRITY']='INDETERMINATE'
 for quality in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','CSV_INTEGRITY'):
  if any(s.get(quality)=='FAIL' for s in sessions):result[quality]='FAIL'
  elif any(quality in s and s.get(quality)!='PASS' for s in sessions):result[quality]='INDETERMINATE' if result.get(quality)=='PASS' else result.get(quality,'FAIL')
 required=('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','CSV_INTEGRITY','SESSION_INTEGRITY')
 result['VERDICT']='PASS' if exit_code==0 and all(result.get(k)=='PASS' for k in required) else 'FAIL'
 result['SESSION_VERDICT']=result['VERDICT']
 return result
