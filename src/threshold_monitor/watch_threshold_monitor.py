#!/usr/bin/env python
import os
import sys
import yaml
import argparse    
import pandas as pd
import time
import glob
from obspy import UTCDateTime
mysql_installed = False
try:
    import mysql.connector as mysql
    mysql_installed = True
except ImportError:
    print("Module mysql is not installed")
import fcntl

def connect_to_db(mysqlParams):
    db = mysql.connect(
        user = mysqlParams['user'],
        password = mysqlParams['password'],
        host = mysqlParams['host'],
        database = mysqlParams['database']
    )
    return db

def df2mysql(data, db):
    #print(data)
    query_cursor = db.cursor()
    if data['station'] == "VMT":
        sta_id = 13
    else:
        sta_id = int(data['station'][-2:])
    query = f'''UPDATE occ_display SET system_status={int(data['status']=='ON')} WHERE station_id={sta_id};'''
    query_cursor.execute(query)
    db.commit()

# parse command line arguments
parser = argparse.ArgumentParser(description='monitoring latency and threshold CSV files')
parser.add_argument('-v', '--verbose', action='count', default=0, help='turn verbose output on')
#parser.add_argument('-v', '--verbose', action='store_true', help='turn verbose output on')
parser.add_argument('-r', '--refresh_interval', action='store', dest='refresh_interval', default=10.0, type=float, help='refresh_interval in seconds')
parser.add_argument('-o', '--outputdir', action='store', dest='outputdir', default=os.getcwd(), help='output directory to monitor')
parser.add_argument('-p', '--parameterfile', action='store', dest='parameterfile', default=sys.argv[0].replace('threshold_monitor.py', 'threshold_monitor.yml'), help='YAML config file path/name')
parser.add_argument('-i', '--iterations', action='store', dest='max_iterations', default=1e9, type=int, help='number of iterations (set low for testing)')
command_line_dict = vars(parser.parse_args(sys.argv[1:]))

# load parameter file into params dict
with open(command_line_dict["parameterfile"], 'r') as yml:
    params = yaml.safe_load(yml)

# override params attributes if same set on command line
for k, v in command_line_dict.items():
    if v is not None:
        params[k] = v

if mysql_installed:
    db = connect_to_db(params['mysql_info'])
else:
    params['verbose'] = True # force verbose mode if not updating a MySQL table, since otherwise no output

def get_last_N_lines(csvfile, N=3):
    while True:
        try:
            with open(csvfile, 'r') as fptr:
                fcntl.flock(fptr, fcntl.LOCK_EX | fcntl.LOCK_NB) # lock the file
                """
                first_line = fptr.readline()
                for line in fptr:
                    pass
                last_line = line
                lines = first_line + '\n' + last_line + '\n'
                df = pd.read_clipboard(lines, sep=',')
                """
                df = pd.read_csv(csvfile)
                df = df.tail(N)
                fcntl.flock(fptr, fcntl.LOCK_UN)
                fptr.close()
                #print(df)
                break
        except:
            time.sleep(0.05)
    return df

iterations = 0
last_alarmtime = UTCDateTime(1900,1,1)
last_latency = 0
while iterations < params['max_iterations']: # max_iterations defaults to 1e9 which at refresh_interval=10 seconds is about 300 years
    
    utcnow = UTCDateTime()
    alarm_seed_ids = []
    max_current_latency = 0

    if params['verbose']:
        os.system('clear') # if logging output to Terminal, this will keep refreshing terminal, which is nice
        print('\n',sys.argv[0],': Updating at ',utcnow)

    # Check last line of each latency CSV file (one per station)
    latency_listofdicts = []
    latencyfiles = glob.glob(os.path.join(params['outputdir'], 'latency*.csv'))
    if len(latencyfiles)==0:
        print(f'Warning: no latency CSV files found in {params["outputdir"]}')
    else:
        for latencyfile in latencyfiles:
            epoch_mtime = os.path.getmtime(latencyfile)
            seconds_ago = utcnow - UTCDateTime(epoch_mtime)
            df = get_last_N_lines(latencyfile, 1) # uses fnctl instead
            if len(df)>0:
                last_row = df.iloc[-1]
                station = last_row['seed_id'].split('.')[1]
                seconds_ago = utcnow - UTCDateTime(last_row["endtime"])
                latency_listofdicts.append({'station':station, 'latency':round(seconds_ago,1)})

                if seconds_ago > params['maximum_latency'] and seconds_ago > last_latency + 0.5:
                    alarm_seed_ids.append(last_row['seed_id'])
                    if seconds_ago > max_current_latency:
                        max_current_latency = seconds_ago
                            
        # We still only send an alarm if we are beyond the latency_alarm_timeout period 
        if alarm_seed_ids:
            if utcnow > last_alarmtime + params['latency_alarm_timeout']: # did we exceed latency criteria for any seed_id?
                # SCAFFOLD: ADD CODE HERE TO SEND A LATENCY ALARM VIA SLACK
                last_alarmtime = utcnow
        last_latency = max_current_latency                

        # Check last line of each threshold CSV file (one per station)
        threshold_listofdicts = []
        thresholdfiles = glob.glob(os.path.join(params['outputdir'], 'threshold*.csv'))
        if len(thresholdfiles)==0:
            print(f'Warning: no threshold CSV files found in {params["outputdir"]}')
        else:
            for thresholdfile in thresholdfiles:
                epoch_mtime = os.path.getmtime(thresholdfile)
                seconds_ago = utcnow - UTCDateTime(epoch_mtime)
                # we get last 3 rows of a threshold CSV file - for HNZ, HNN, HNE
                df = get_last_N_lines(thresholdfile, 3) # uses fnctl instead
                if len(df)>0:
                    # sort in ascending order by value (PGA), so the last row will have the highest threshold status
                    df.sort_values('value', inplace=True)
                    last_row = df.iloc[-1]
                    station = last_row['seed_id'].split('.')[1]
                    seconds_ago = utcnow - UTCDateTime(last_row["peaktime"])
                    threshold_listofdicts.append({'station':station, 'threshold_latency':round(seconds_ago,1), 'status':last_row['status']})

            # create and merge dataframes on station key
            latencydf = pd.DataFrame(latency_listofdicts)
            thresholddf = pd.DataFrame(threshold_listofdicts)
            summarydf = latencydf.copy().merge(thresholddf, how='outer')

            # output the merged dataframe
            if params['verbose'] and not mysql_installed:
                print(summarydf.sort_values(by='station'))

            # update MySQL occ_display table
            if mysql_installed:
                summarydf.apply(lambda data: df2mysql(data, db), 1)

    # wait before looping again
    time.sleep(params['refresh_interval'])
    iterations += 1
