#!/usr/bin/env python
# run this like:
# pytest -v test_threshold_monitor.py
# or with run_tests.sh
import os, sys, glob
import obspy
import pandas as pd
import time
import subprocess 
import yaml
import inspect
rundir = os.getcwd() 
srcdir = os.path.join(rundir, 'src', 'threshold_monitor')
sys.path.append(srcdir)
os.chdir(srcdir)
import wf2obspy
import calib2obspy
testsdir = os.path.join(rundir, 'tests')
PF = os.path.join(srcdir, "threshold_monitor.yml")
DI_EXE = os.path.join(srcdir, 'data_ingestion.py')
TM_EXE = os.path.join(srcdir, 'threshold_monitor.py')
OPTIONS = " -v -b -l "
NSLC1 = 'AK.PS01..HNZ'
NSLC3 = 'AK.PS01..HN?'
NSLCall = 'AK.*..HN?'
NSLCPSall = 'AK.PS*..HN?'
DURATION=60 # default seconds to run tests for. overrides YML file. alarms are run for 4 times this long
outputTop = os.path.join(rundir, 'output', 'testing')
if os.path.isdir(outputTop):
    os.system(f"rm -rf {outputTop}/*")
else:
    os.makedirs(outputTop)
PYTHON = sys.executable

def get_times(starttime=None, duration=DURATION):
    if not starttime:
        starttime = obspy.UTCDateTime()
        endtime = starttime + duration
    return starttime, endtime

def run_command(cmd='--version', outfile='test.log'):
    cmd_list = cmd.split()
    cmd_list.insert(0, PYTHON)
    print(cmd_list)
    with open(outfile, 'w') as fptr:
        ans = subprocess.run(cmd_list, capture_output=False, stdout=fptr, stderr=fptr)
    return ans.returncode

def get_params():
    params = None
    inputfile = PF
    with open(inputfile, 'r') as yml:
        params = yaml.safe_load(yml) 
    return params

def get_inventory_from_iris():
    params = get_params()
    from obspy.clients.fdsn.client import Client
    client = Client('iris')
    starttime = obspy.UTCDateTime(2007,1,1)
    endtime = obspy.UTCDateTime()
    inv = client.get_stations(network='AK', station='PS*', channel='HN*', starttime=starttime, endtime=endtime, level='response')
    inv2 = client.get_stations(network='AK', station='VMT', channel='HN*', starttime=starttime, endtime=endtime, level='response')
    inv.extend(inv2)
    print(inv)
    inv.write(params['xmlfile'], format='STATIONXML')

def run_job(EXE, api, starttime, endtime, nslc, outputdir=None, pffile=PF):
    print("nslc=",nslc)
    duration = round(endtime-starttime)
    PROGNAME = os.path.basename(EXE).replace('.py', '')
    if not outputdir:
        outputdir = os.path.join(outputTop, f'{inspect.stack()[2][3]}')
    if not os.path.isdir(outputdir):
        os.makedirs(outputdir)
    #os.chdir(outputdir)
    logfile = os.path.join(outputdir, 'run.log')

    # run threshold_monitor.py
    cmd = f" {EXE} {OPTIONS}  -p {pffile} -a {api} -s {starttime} -e {endtime} -n {nslc} -o {outputdir}" # > {logfile} &"
    print(cmd)
    returncode = run_command(cmd, outfile=logfile)

    # change directory back
    #os.chdir(rundir)   
    return returncode 

def run_data_ingestion(api='orb2obspy', starttime=None, duration=DURATION, nslc=NSLC1):
    starttime, endtime = get_times(starttime=starttime, duration=duration)
    return run_job(DI_EXE, api, starttime, endtime, nslc)

def run_threshold_monitor(api='orb2obspy', duration=DURATION, starttime=None, nslc=NSLCall, pffile=PF):
    # api is one of ['orb2obspy', 'slink2obspy', 'datascope2obspy']
    starttime, endtime = get_times(starttime=starttime, duration=duration)
    return run_job(TM_EXE, api, starttime, endtime, nslc, pffile=pffile)

def process(st):
    st.detrend('constant')
    st.taper(0.1)
    #st.filter('highpass', freq=0.1, corners=2)
    st.filter('bandpass', freqmin=0.5, freqmax=10.0, corners=2)

def run_calib2obspy(nslc, starttime=None, endtime=None, return_streams=False):
    if not starttime:
        starttime = obspy.UTCDateTime()-90
        endtime = starttime+30
    while obspy.UTCDateTime() < endtime:
        time.sleep(1)
    net, sta, loc, chan = nslc.split('.')
    print(nslc, net, sta, loc, chan)
    straw = wf2obspy.get_waveforms(net, sta, loc, chan, starttime, endtime)  
    seed_ids = [tr.id for tr in straw] 
    responses = calib2obspy.get_stations(seed_ids)
    calib2obspy.attach_response(straw, responses)
    #pre_filt={'type':'highpass', 'freq':0.1, 'corners':2}
    pre_filt=None
    stproc = straw.copy()
    process(stproc)
    stcal = stproc.copy()
    calib2obspy.remove_response(stcal, pre_filt=pre_filt)
    if return_streams:
        return straw, stproc, stcal
    return 0 

def join_times(df, pretime, posttime):
    run_dict={}
    for index, row in df.iterrows():
        starttime = row['datetime'] - pretime
        endtime = row['datetime'] + posttime
        nslc = f"AK.{row['station']}..{row['channel']}"

        if nslc in run_dict:
            nslc_dict = run_dict[nslc]
            #prevstarttime = nslc_dict['starttime'][-1]
            prevendtime = nslc_dict['endtime'][-1]
            if starttime < prevendtime:
                #print('changing endtime')
                nslc_dict['endtime'][-1] = endtime
            else:
                #print('APPENDING')
                nslc_dict['starttime'].append(starttime)
                nslc_dict['endtime'].append(endtime)
        else:
            #print('NEW')
            nslc_dict = {'starttime': [starttime], 'endtime': [endtime]}
            run_dict[nslc] = nslc_dict

    return run_dict

alarms_to_match_csv = os.path.join(testsdir, 'TM_alarms.csv')
alarms_matched_csv = os.path.join(outputTop, 'matched_alarms.csv')
def run_alarms(pretime=DURATION*2, posttime=DURATION*2, api='datascope2obspy'):
    df = pd.read_csv(alarms_to_match_csv)
    df['datetime'] = pd.to_datetime(df['datetime'], format='%m/%d/%Y %H:%M:%S')
    df['datetime'] = [obspy.UTCDateTime(t) for t in df['datetime']]
    df = df.sort_values(by='datetime')
    run_dict = join_times(df, pretime, posttime)
    df = df.rename(columns={'datetime':'alarmtime', 'level':'status'})
    #df.to_csv(alarms_to_match_csv.replace('.csv', '_v2.csv'), index=False)

    lod = []
    for nslc, nslc_dict in run_dict.items():
        for starttime, endtime in zip(nslc_dict['starttime'], nslc_dict['endtime']):
            meantime = starttime + (endtime-starttime)/2
            mtime = meantime.strftime('%Y%m%d%H%M')
            outputdir = os.path.join(outputTop, f"test_alarm_{api}_{mtime}")
            run_job(TM_EXE, api, starttime, endtime, nslc[0:-1]+'?', outputdir=outputdir)
            #run_job(TM_EXE, api, starttime, endtime, nslc, outputdir=outputdir)
            more_alarm_pngs = glob.glob(os.path.join(outputdir, 'alarm_*.png'))
            for alarmpng in more_alarm_pngs:
                _, alarmtime, station, status = os.path.basename(alarmpng).split('_')
                this_alarm = {'alarmtime': obspy.UTCDateTime.strptime(alarmtime,"%Y%m%d%H%M%S%F"), 'station':station, 'status':status.split('.')[0].lower()}
                lod.append(this_alarm)
    dfalarm = pd.DataFrame(lod)
    dfalarm['time_match']=False
    dfalarm['status_match']=False
    print(dfalarm)
    # now go through the alarms in the original dataframe (df) and check there is a matching alarm in dfalarm
    for index, row in df.iterrows():
        matchdf = dfalarm.copy()[dfalarm['station']==row['station']]
        matchdf['timediff'] = abs(matchdf['alarmtime'] - row['alarmtime'])
        matchdf = matchdf[matchdf['timediff'] <= 1.0]
        if len(matchdf)==0:
            # no matches
            continue
        elif len(matchdf)>1:
            mintimediff = matchdf['timediff'].min()
            matchdf = matchdf[matchdf['timediff']==mintimediff]
        rownum = matchdf.index[0]
        dfalarm.loc[rownum, 'time_match'] = True
        if matchdf.loc[rownum, 'status'] == row['status']:
            dfalarm.loc[rownum, 'status_match'] = True
    #dfalarm['full_match'] = dfalarm['time_match'] & dfalarm['status_match'] # same at status_match
    print(dfalarm)
    dfalarm.to_csv(alarms_matched_csv, index=False)

####### TESTS BEGIN HERE

def test_command():
    assert run_command()==0

def test_yml():
    params = get_params()
    print(params)
    assert params

def test_inventory():
    params = get_params()
    print(params)
    assert os.path.isfile(params['xmlfile'])
    inv = obspy.read_inventory(params['xmlfile'], format='STATIONXML')
    assert isinstance(inv, obspy.Inventory)

def test_calib2obspy_1channel():
    assert run_calib2obspy(NSLC1)==0

def test_iris_vs_aec_calibrations():

    def compare_streams(st1, st2, outfile, stime, etime):
        for tr in st1:
            tr.stats.location = 'IR'
        for tr in st2:
            tr.stats.location = 'UA'
        st = st1 + st2
        st = st.select(component='Z')
        st.trim(starttime=stime, endtime=etime)
        st.merge()
        #st.select(component='Z').plot(equal_scale=False, outfile=outfile)
        last_sta = 'DUMM'
        last_val = 0.0
        percent_diff_max = 5.0
        for tr in st: # this logic depends on only having Z channels
            val = tr.std()
            sta = tr.stats.station
            print(f'{tr.id}: {val:e}')
            if sta == last_sta:
                percent_diff=abs(100*(1.0-val/last_val))
                print(f'{sta} percent_diff={percent_diff:.2f} ')
                if percent_diff > percent_diff_max:
                    raise IOError(f'calibration disagrement between IRIS and AEC data for station {sta}')
            last_sta = sta
            last_val = val

    from obspy.clients.fdsn import Client
    t = obspy.UTCDateTime()
    stime = t-300
    etime = t-240
    pretrig=60
    outfile=os.path.join(outputTop, 'raw_stream.png')
    remove_instrument_response = False # True

    # get raw, processed, and calibration streams from AEC
    straw, stproc, stcal = run_calib2obspy(NSLCPSall, starttime=stime-pretrig, endtime=etime+pretrig, return_streams=True)

    # get raw data from IRIS
    client = Client("IRIS")
    t = obspy.UTCDateTime()
    stiraw = client.get_waveforms("AK", "PS*", "", "HN?", stime-pretrig, etime+pretrig)
    
    # process IRIS data
    stiproc = stiraw.copy()
    process(stiproc)

    # correct IRIS data
    stical = stiproc.copy()
    get_inventory_from_iris()
    params = get_params()
    inv = obspy.read_inventory(params['xmlfile'], format='STATIONXML')
    stical.attach_response(inv)
    tnow = time.time()
    if remove_instrument_response:
        stical.remove_response(output='ACC')
    else:
        for tr in stical:
            if 'response' in tr.stats:
                gain = tr.stats.response.instrument_sensitivity.value
                print(tr.id, gain)
                tr.data /= gain
            else:
                print(f'no response attribute exists for {tr.id}')
    print('Elapsed time: ', time.time()-tnow)

    # compare raw data streams
    print('\nRAW DATA')
    compare_streams(stiraw, straw, outfile, stime, etime)    
            
    # compare processed data streams
    print('\nPROCESSED DATA')
    compare_streams(stiproc, stproc, outfile.replace('raw', 'proc'), stime, etime)    

    # compare calibrated data streams
    print('\nCALIBRATED DATA')
    compare_streams(stical, stcal, outfile.replace('raw', 'cal'), stime, etime) 

def test_data_ingestion_1channel_orb2obspy():
    assert run_data_ingestion(api='orb2obspy', starttime=None, duration=DURATION, nslc=NSLC1)==0

def test_data_ingestion_1station_orb2obspy():
    assert run_data_ingestion(api='orb2obspy', starttime=None, duration=DURATION, nslc=NSLC3)==0    

def test_data_ingestion_1channel_slink2obspy():
    assert run_data_ingestion(api='slink2obspy', starttime=None, duration=DURATION, nslc=NSLC1)==0

def test_data_ingestion_1station_slink2obspy():
    assert run_data_ingestion(api='slink2obspy', starttime=None, duration=DURATION, nslc=NSLC3)==0

def test_data_ingestion_1channel_datascope2obspy():
    assert run_data_ingestion(api='datascope2obspy', starttime=None, duration=DURATION, nslc=NSLC1)==0

def test_data_ingestion_1station_datascope2obspy():
    assert run_data_ingestion(api='datascope2obspy', starttime=None, duration=DURATION, nslc=NSLC3)==0

def test_threshold_monitor_1channel_orb2obspy():
    assert run_threshold_monitor(api='orb2obspy', starttime=None, duration=DURATION, nslc=NSLC1)==0

def test_threshold_monitor_1station_orb2obspy():
    assert run_threshold_monitor(api='orb2obspy', starttime=None, duration=DURATION, nslc=NSLC3)==0

def test_threshold_monitor_allchannels_orb2obspy():
    assert run_threshold_monitor(api='orb2obspy', starttime=None, duration=DURATION, nslc=NSLCall)==0

def test_threshold_monitor_allchannels_slink2obspy():
    assert run_threshold_monitor(api='slink2obspy', starttime=None, duration=DURATION, nslc=NSLCall)==0

def test_threshold_monitor_allchannels_datascope2obspy():
    assert run_threshold_monitor(api='datascope2obspy', starttime=None, duration=DURATION, nslc=NSLCall)==0    

def test_alarms():
    run_alarms(pretime=DURATION, posttime=DURATION)
"""
def test_do_alarm_times_match():
    df = pd.read_csv(alarms_matched_csv)
    a=df['time_match'].all()
    assert a==True

def test_do_alarm_statuses_match():
    df = pd.read_csv(alarms_matched_csv)
    a = df['status_match'].all()
    assert a==True

def test_CIGO_power_cycle():
    # database from https://akearthquake.slack.com/archives/C06P4LHR0EL/p1723661171345589
    dbpath = '/aec/db/instrument_test/archive/inst_testdb_2024_08'
    #match = 'HT_10627_HN?/GENC/Q8'
    thisnslc = 'HT.10627..HNZ'
    net, sta, loc, chan = thisnslc.split('.')
    if os.path.isfile(dbpath + '.wfdisc'):
        print('database wfdisc exists')
        os.system(f"grep 10627 {dbpath}.wfdisc | grep NZ")
    else:
        print(dbpath, ' not found')

    # Nate power cycles from https://akearthquake.slack.com/archives/C06P4LHR0EL/p1723680619247289
    '''
    I powered down and back up the Q8 today.  All times are AK local.
    First cycle:
    Disconnected power at 15:28.  Q8 powered down by 15:30.  Reconnected power at 15:35.  Startup completed by 15:40.
    Second cycle:
    Disconnected power at 15:50.  Q8 powered down by 15:52.  Reconnected power at 16:02.  Startup completed by 16:10.
    '''
    startt = obspy.UTCDateTime(2024, 8, 14, 15, 0, 0) + 8*3600 # add 8 hours from AK summer time to UTC
    endt = obspy.UTCDateTime(2024, 8, 14, 16, 20, 0) + 8*3600
    pffile = os.path.join(testsdir, 'threshold_monitor_10627.yml')
    #assert run_threshold_monitor(api='datascope2obspy', starttime=stime, duration=etime-stime, nslc=thisnslc, pffile=pffile)==0
    st = wf2obspy.get_waveforms(net, sta, loc, chan, startt, endt, dbname=dbpath)  
    assert isinstance(st, obspy.Stream)
    print(st)
    assert len(st)>0
    st.plot(outfile=os.path.join(outputTop, 'test_CIGO_power_cyle.png'))
"""
if __name__ == "__main__": # useful to put specific tests here when they fail and run this under python instead of pytest
   print('running main')
   test_command()
   test_yml()
   test_inventory()
   #test_calib2obspy_1channel()
   #test_iris_vs_aec_calibrations()
   test_data_ingestion_1channel_orb2obspy()
   test_data_ingestion_1station_orb2obspy()
   test_data_ingestion_1channel_slink2obspy()
   test_data_ingestion_1station_slink2obspy()
   test_data_ingestion_1channel_datascope2obspy()
   test_data_ingestion_1station_datascope2obspy()
   test_threshold_monitor_1channel_orb2obspy()
   test_threshold_monitor_1station_orb2obspy()
   test_threshold_monitor_allchannels_orb2obspy()
   test_threshold_monitor_allchannels_slink2obspy()
   test_threshold_monitor_allchannels_datascope2obspy()
   test_alarms()
   test_do_alarm_times_match()
   test_do_alarm_statuses_match()
   #test_CIGO_power_cycle()
