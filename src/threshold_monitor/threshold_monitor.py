#!/usr/bin/env python
from obspy import UTCDateTime
tstart = UTCDateTime()
import os
import sys
import numpy as np
import data_ingestion
import subprocess # for sending alarms
import pandas as pd
import matplotlib.pyplot as plt
import multiprocessing as mp
import re
import fcntl
mysql_imported = False
try:
    import mysql.connector as mysql
    mysql_imported = True
except:
    print('mysql not imported')
################################################################################
###                            CLASSES                                       ###
################################################################################

class thresholdHistory(object):
    ROWNUM = -1
    def __init__(self, thresholds, station, outputdir = None, seconds_to_keep=60):
        if outputdir: 
            self.outputdir = outputdir
        else:
            self.outputdir = UTCDateTime().isoformat()
        self.rownum = []
        self.seed_id = []
        self.starttime = []
        self.endtime = []
        self.peaktime = []
        self.value = []
        self.status = []
        self.thresholds = thresholds
        self.seconds_to_keep = seconds_to_keep
        self.last_trimmed_time = UTCDateTime()
        self.previous_state = {}
        self.secondsPerPacket = None
        self.outputdir = outputdir
        self.station = station
        self.csvfile = os.path.join(self.outputdir, f'threshold_history_{station}.csv')
        # start the output file
        row = 'rownum,seed_id,starttime,endtime,peaktime,value,status\n'
        data_ingestion.append_to_csvfile(self.csvfile, row) 

    def update(self, seed_id, starttime, endtime, peaktime, value, status):

        # update thresholdHistory attributes - these are all lists and there is one element per Trace from each packet Stream
        self.ROWNUM += 1
        self.rownum.append(self.ROWNUM)
        self.seed_id.append(seed_id)
        self.starttime.append(starttime)
        self.endtime.append(endtime)
        self.peaktime.append(peaktime)
        self.value.append(value)
        self.status.append(status)

        # update the output file
        row = f'{self.ROWNUM},{seed_id},{starttime},{endtime},{peaktime},{value},{status}' + '\n'
        data_ingestion.append_to_csvfile(self.csvfile, row)        
        
        # trim the object
        if UTCDateTime() > self.last_trimmed_time + self.seconds_to_keep:
            self.trim()
            data_ingestion.trim_csvfile(self.csvfile)
        
        # The following logic is designed to issue a threshold exceedance detection if the status changes upwards only, e.g. OFF -> LOW, or LOW -> MEDIUM, or MEDIUM -> HIGH
        thresholdDetection =  None
        if status == 'OFF' or not seed_id in self.previous_state: # Reset everything
            self.previous_state[seed_id] = {'status':status, 'value':value, 'peaktime':peaktime} 
        elif value>self.previous_state[seed_id]['value'] and status != self.previous_state[seed_id]['status']: # at least LOW, and value increased
            thresholdDetection = {'seed_id':seed_id, 'starttime':starttime, 'endtime':endtime, 'peaktime':peaktime, 'value':value, 'status':status}
        self.previous_state[seed_id] = {'status':status, 'value':value, 'peaktime':peaktime} 
        return thresholdDetection

    def to_dataframe(self):
        df = pd.DataFrame()
        df['rownum'] = self.rownum
        df['seed_id'] = self.seed_id
        df['starttime'] = self.starttime
        df['endtime'] = self.endtime
        df['peaktime'] = self.peaktime
        df['value'] = self.value
        df['status'] = self.status
        return df

    def print(self):
        df = self.to_dataframe()
        print(df)

    def plot(self, outfile='threshold_history.png', load_csv=False):
        timecol = 'starttime'
        if load_csv and self.ROWNUM > 0:
            df = pd.read_csv(self.csvfile)
            df['datetime'] = [UTCDateTime(tstr).datetime for tstr in df[timecol]]  
        else:
            self.trim() # trim so we always have a consistent 10-minute plot, or whatever seconds_to_keep is set to
            df = self.to_dataframe()
            df['datetime'] = [t.datetime for t in df[timecol]]
        units = 'm/s^2'
        seed_ids = df['seed_id'].unique()
        #print('seed_ids: ',seed_ids)
        fig, ax = plt.subplots()
        cols = ['black', 'blue', 'grey']
        for i, seed_id in enumerate(seed_ids):
            thisdf = df[df.seed_id == seed_id]
            ymax = thisdf['value'].max()
            ymin = thisdf['value'].min() 
            threshmax = max(self.thresholds[self.station].values())
            threshmin = min(self.thresholds[self.station].values())
            ymax = max((ymax, threshmax))
            ymin = min((ymin, threshmin))

            df2 = thisdf.copy()
            df2.reset_index(inplace=True)
            df2.plot(ax=ax, x='datetime', y='value', style='.-', label=seed_id[-1], \
                    title=f'peak amplitude vs. time for {self.station}?', 
                    ylim=[ymin/1.5, ymax*1.5], logy=True, color=cols[i])
        ax.set_xlabel(f"Date/Time on {df.loc[0, 'datetime'].strftime('%Y/%m/%d')}") # getting a string here, probably when loading from file
        ax.set_ylabel(f'Peak amplitude ({units})')
            
        handles, labels = ax.get_legend_handles_labels()
        cols = ['r', 'g', 'y']
        i = 0
        station_thresholds = self.thresholds[self.station]
        for k,v in station_thresholds.items():
            handles.append(ax.axhline(y=v, xmin=-1, xmax=1, color=cols[i], linestyle='--', lw=2, label=k.upper()))
            xlims = ax.get_xlim()
            ax.text((xlims[0]+xlims[1])/2, v, k.upper(), color=cols[i], fontsize=12)
            i+=1
        plt.legend(handles=handles)
        plt.savefig(outfile)
        plt.close()

    def trim(self):
        # trim the object lists
        # find index N where self.starttime is within the last self.seconds_to_keep seconds
        N = next(x for x, val in enumerate(self.starttime) if val>self.starttime[-1]-self.seconds_to_keep)
        self.rownum = self.rownum[N:]
        self.seed_id = self.seed_id[N:]
        self.starttime = self.starttime[N:]
        self.endtime = self.endtime[N:]
        self.peaktime = self.peaktime[N:]
        self.value = self.value[N:]
        self.status = self.status[N:]

################################################################################
class MyDataClient(data_ingestion.RealTimeDataClient):

    def __init__(self, params): 
        super().__init__(params)
        self.last_alarm = {'peaktime':UTCDateTime(1900,1,1), 
                           'status': 'OFF',
                           'value': 0.0
                           }

        g = 9.80665 # m/s^2
        for k, v in self.thresholds[self.station].items(): # convert thresholds from str and units g to units m/s**2
            self.thresholds[self.station][k] = float(v) * g
        self.thresholdHistoryObject = thresholdHistory(self.thresholds, self.station, outputdir=self.outputdir)
        if self.verbose:
            print('THRESHOLDS:')
            print(self.thresholds)
        
        # connect to mysql database
        mysql_info = params['mysql_info']
        if mysql_imported:
            self.db = mysql.connect(
                user = mysql_info['user'],
                password = mysql_info['password'],
                host = mysql_info['host'],
                database = mysql_info['database']
            )

    def computePGA(self):
        st = self.currentPacket
        pga_dict = dict()
        # find max absolute value, and time of that max value
        for tr in st:
            x = np.absolute(tr.data)
            x_max = np.max(x)
            ind_max = np.argmax(x)
            time_max = tr.stats.starttime + tr.stats.delta * ind_max
            # pga_dict has starttime and endtime of packet, peak value, and time of that peak value (which falls between start and end time)
            pga_dict[tr.id] = {'value':x_max, 'starttime':tr.stats.starttime, 'endtime':tr.stats.endtime, 'peaktime':time_max}
        return pga_dict

    def PGA2thresholddetections(self, tracemax):
        thresholdDetections = []
        station_thresholds = self.thresholds[self.station]
        for seed_id in tracemax.keys():
            this = tracemax[seed_id]
            status = 'OFF'

            # the logic here does not assume that 'OFF', 'LOW', 'MEDIUM' and 'HIGH' will always be the threshold labels we use
            # or that the threshold levels in station_thresholds are in numerically increasing order of threshold level
            # this allows us to change labels and/or levels in parameter file at any time
            highest_v = 0.0 # the highest threshold value triggered at
            for k, v in station_thresholds.items(): # at this point, k is like 'low' or 'medium', and v is corresponding threshold level in m/s^2
                if this['value'] > v and v > highest_v:
                    highest_v = v
                    status = k.upper() # e.g. turn 'low' into 'LOW'. 

            thisThresholdDetection = self.thresholdHistoryObject.update(seed_id, this['starttime'], this['endtime'], \
                                                                        this['peaktime'], this['value'], status)
            if thisThresholdDetection:
                thresholdDetections.append(thisThresholdDetection)
        return thresholdDetections            

    def send_alarm(self, seed_id, starttime, endtime, peaktime, value, status, thresholdDetections):
        now = UTCDateTime()
        subject = f"{status} threshold Alarm at {self.station} at {peaktime}"
        body = subject + '\n'
        for td in thresholdDetections:
            body += f"Threshold Alarm at {td['seed_id']} at {td['peaktime'].strftime('%Y-%m-%dT%H:%M:%S')} exceeded {td['status']} Threshold. Level now {td['value']}"
        pngfile = os.path.join(self.outputdir, f'threshold_alarm_{peaktime.strftime("%Y%m%d%H%M%S%F")}_{self.station}_{status}.png')
        self.thresholdHistoryObject.plot(outfile=pngfile, load_csv=False)
        data_ingestion.send_email_alarm(subject, body, self.email_list, pngfile=pngfile, verbose=True)

        # send update to mysql database
        if mysql_imported:
            query_cursor = self.db.cursor()
            if self.station == "VMT":
                sta_id = 13
            else:
                sta_id = int(self.station[-2:])

            if status in ["LOW", "MED", "HIGH"]:
                query = f'''UPDATE occ_display SET {status.lower()}=1 WHERE station_id={sta_id};'''
            else:
                query = f'''UPDATE occ_display SET 'low'=0, 'med'=0, 'high'=0 WHERE station_id={sta_id};'''
            
            query_cursor.execute(query)
            self.db.commit()


    def thresholddetections2alarms(self, thresholdDetections):
        ''' force alarm only at station level, not individual channels
        so we now track last alarm issued and use threshold_alarm_timeout parameter '''
        #print('thresholdDetections = ', thresholdDetections) # probably important enough to log even if verbose=False

        ''' Note that we have 1 station per thread, so we can only have 3 channels here. And we collapse from potentially
        3 threshold exceedance detections to 1 alarm based on the channel with the highest PGA value '''
        maxvalue = 0.0
        for td in thresholdDetections:
            if td['value'] > maxvalue:
                maxvalue = td['value']
                status = td['status']
                peaktime = td['peaktime']
                starttime = td['starttime']
                endtime = td['endtime']
                seed_id = td['seed_id']

        ''' We still only send an alarm if we are beyond the threshold_alarm_timeout period OR the status has increased, e.g. from LOW to MEDIUM'''
        if peaktime > self.last_alarm['peaktime'] + self.threshold_alarm_timeout or (maxvalue > self.last_alarm['value'] and status!=self.last_alarm['status']):
            self.send_alarm(seed_id, starttime, endtime, peaktime, maxvalue, status, thresholdDetections)
    
    def analyze(self):

        return # SCAFFOLD
 
        pga_dict = self.computePGA()
        self.update_timings('computing_max')

        # threshold exceedance
        thresholdDetections = self.PGA2thresholddetections(pga_dict)
        self.update_timings('threshold_exceedance')

        # alarm decision making
        if len(thresholdDetections) > 0:
            self.thresholddetections2alarms(thresholdDetections)

################################################################################
###                            FUNCTIONS                                     ###
################################################################################
def parse_station_matches(params): 
    ''' GT 20240811: this was added by Luke and it actually seems to require that station is defined in params['thresholds']
    so default is obsolete, and matches params['nslc'] which is a regular expression. not clear if this will
     work for antelope and non-antelope based data sources '''
    matched_nslc = []
    for k in params["thresholds"].keys():
        sta = params['nslc'].split('.')[1] # get just the station
        sta_regex = sta.replace('?', '.').replace('*', '.*') # switch wildcards for regex versions

        # check that this station matches the given nslc
        if re.fullmatch(sta_regex, k) is not None:
            # add to matched_nslc, replacing sta part with just this station
            sta_params = params.copy()
            sta_nslc = params["nslc"].split('.')
            sta_nslc[1] = k
            sta_params["nslc"] = '.'.join(sta_nslc)
            matched_nslc.append(sta_params)
    
    return matched_nslc

def run_parallel(params):
    datahandler = MyDataClient(params)
    datahandler.run()
    datahandler.close()
    return datahandler

def main(argv):

    ###########################################################################
    # SETTING UP PARAMETERS FROM COMMAND LINE & PARAMETER FILE
    ###########################################################################
    params = data_ingestion.get_params(argv) 
    
    ###########################################################################
    # THIS IS WHERE THE WORK GETS DONE
    ###########################################################################

    param_list = parse_station_matches(params)

    with mp.Pool(processes=len(param_list)) as mp_pool:
        datahandlers = mp_pool.map(run_parallel, param_list)
        mp_pool.close()
        mp_pool.join()

    ###########################################################################
    # THIS IS ALL ABOUT REPORTING WHAT HAPPENED
    ########################################################################### 

    for datahandler in datahandlers:
        datahandler.report()
        datahandler.thresholdHistoryObject.print() # unique
        datahandler.thresholdHistoryObject.plot(outfile=os.path.join(datahandler.outputdir, f'thresholds_{datahandler.station}.png'), load_csv=True) # seed_id is automatically added to the file pattern within plot function 

# THIS GETS CALLED WHEN PROGRAM RUN FROM COMMAND LINE        
if __name__ == "__main__":
    main(sys.argv) 
    t_end = UTCDateTime()
    print(f'Finished after {t_end - tstart} seconds')
