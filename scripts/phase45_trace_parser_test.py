#!/usr/bin/env python3
from pathlib import Path
import tempfile
from phase43_trace_state import collect_states

# xctrace encodes repeated duration/TID values as references as well as strings.
xml = '''<root>
<row><start-time id="s0">0</start-time><thread id="t"><tid id="tid">7</tid></thread><thread-state id="r">Running</thread-state><duration id="d">1000</duration></row>
<row><start-time id="s1">1000</start-time><thread ref="t"/><thread-state id="p">Preempted</thread-state><duration ref="d"/></row>
<row><start-time id="s2">2000</start-time><thread id="t2"><tid ref="tid"/></thread><thread-state ref="r"/><duration ref="d"/></row>
</root>'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'states.xml';path.write_text(xml)
    assert collect_states(path, 7) == [(0, 1000, 'Running'), (1000, 2000, 'Preempted'), (2000, 3000, 'Running')]
print('Trace scalar and thread reference decoding PASS')
