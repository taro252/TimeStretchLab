from phase52_verdict import classify,NUMERIC
r={k:'0' for k in NUMERIC};r.update(output_frames='100',produced_frames='100',consumed_frames='100',presented_frames='100',sample_rate='48000',callback_allocations_measured='1',raw_pcm_sha256='a'*64,state='Ended',reason='EOS',eos='1',route_stopped='0',AUDIO_QUALITY='PASS',MEASUREMENT_QUALITY='PASS')
assert classify(r,0)['VERDICT']=='PASS'
for k in NUMERIC:
 for bad in ('nan','inf','-inf','-1','missing'):
  q=dict(r);q[k]=bad;assert classify(q,0)['VERDICT']=='FAIL'
 q=dict(r);del q[k];assert classify(q,0)['VERDICT']=='FAIL'
for k in ('missing_frames','underrun_calls','callback_overruns','host_cadence_errors','sample_errors','records_dropped'):
 q=dict(r);q[k]='1';assert classify(q,0)['VERDICT']=='FAIL'
assert classify(r,2)['VERDICT']=='FAIL';assert classify(r,0,remaining_actions=1)['VERDICT']=='FAIL'
q=dict(r,MEASUREMENT_QUALITY='FAIL');assert classify(q,0)['MEASUREMENT_QUALITY']=='FAIL'
q=dict(r,state='Stopped',reason='RouteChanged',eos='0',route_stopped='1',consumed_frames='20',presented_frames='20')
assert classify(q,0)['VERDICT']=='FAIL' and classify(q,0,expected_route=True)['VERDICT']=='PASS'
print('Required-field/nonfinite/supply/measurement/pending/route strict verdict PASS')
