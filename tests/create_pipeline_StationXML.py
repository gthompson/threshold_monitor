#!/usr/bin/env python
import os
repodir = os.path.join(os.getenv('HOME'), 'Developer', 'GitHub', 'antelope')
projectdir = os.path.join(repodir, 'bin', 'rt', 'orbtm', 'orbtm_simulate')
ANTELOPE=os.getenv('ANTELOPE')
EXE=os.path.join(ANTELOPE,'bin','db2stationxml')
XMLFILE=os.path.join(projectdir,'pipeline_stations_antelope.xml')
DB='/aec/db/stations/master_stations'
cmd = f'{EXE} -v -o {XMLFILE} -L response -s "PS.*|VMT" {DB}'
print(cmd)
os.system(cmd)