"""Strict developer-player verdict; expected route stops are never normal EOS."""
import math,re
NUMERIC=('output_frames','produced_frames','consumed_frames','presented_frames','missing_frames','underrun_calls','max_continuous_missing','rejected_writes','callback_allocations_measured','callback_cpp_allocations','callback_overruns','host_missing','host_backwards','host_cadence_errors','sample_errors','hal_window_misses','records_dropped','sample_rate')
def classify(row,exit_code,expected_route=False,remaining_actions=0):
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
