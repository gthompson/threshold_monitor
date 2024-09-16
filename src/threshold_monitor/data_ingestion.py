#!/usr/bin/env python
import obspy
tstart = obspy.UTCDateTime()
import sys
import numpy as np
import yaml
import argparse
import time
# for latency or timings
import os
import pandas as pd
import matplotlib.pyplot as plt
import subprocess
import fcntl
UNAME = os.environ.get('USER')
HOSTNAME = os.uname().nodename
################################################################################
###                            CLASSES                                       ###
################################################################################

class RealTimeDataClient(object):

    def __init__(self, params):
        self.secondsPerPacket = 1.0 # use this for datascope simulated packet size?   
        self.bufferSecs = 0.0
        self.filterdef = None
        self.remove_instrument_response = False # defaults to just using overall sensivity (same as calib)
        for param in params:
            setattr(self, param, params[param])
    
        self.network, self.station, self.location, self.channel = params['nslc'].split('.')

        if not 'datasource' in params:
            self.datasource = 'default'

        if self.api=='datascope2obspy':
            from datascope2obspy import DatascopeClient
            self.client = DatascopeClient(self.datasource, secondsPerPacket=self.secondsPerPacket, starttime=self.starttime, mode=self.mode)

        elif self.api=='orb2obspy':
            from orb2obspy import OrbserverClient
            self.client = OrbserverClient(self.datasource, starttime=self.starttime, nslc=params['nslc'])

        elif self.api=='slink2obspy':
            from slink2obspy import SlinkClient
            self.client = SlinkClient(self.datasource)
        self.client.select_stream(self.network, self.station, self.location, self.channel) 

        if self.benchmark:
            self.timingObj = timings(tstart)
        if self.latency_on:
            # keep at least 10 minutes (600 s) of latency info in RAM
            self.latencyObj = latency(self.station, \
                                      seconds_to_keep=60, \
                                      maximum_latency=self.maximum_latency, \
                                      email_list=self.email_list, \
                                      outputdir=self.outputdir, \
                                      alarm_timeout=self.latency_alarm_timeout) # creates a latency object
        self.duration = self.endtime - self.starttime

        ### The following line relate to using a waveform packet - which is just a Stream object ###
        self.currentPacket = None
        self.npackets = 0
        
        ### end of packet stuff ### 

        ### The folowing lines relate to using a waveform buffer that is long enough to support filtering ###
        self.currentBuffer = None
        if self.filterdef:
            bufferSecsNeededForFilter = 2.0/self.filterdef['freq'][0] 
            if bufferSecsNeededForFilter > self.bufferSecs:
                print(f"Expanding buffer size from {self.bufferSecs} to {bufferSecsNeededForFilter} seconds, because of requested filter")
                self.bufferSecs = bufferSecsNeededForFilter
        ### end of buffer stuff ###
        
        # calibration information
        self.inventory = None
        self.response_update_interval = 600 # update every 600 seconds
        self.response_last_update_time = None
       
        # show all attributes?
        if self.verbose:
            print(f'{self.__class__.__name__} attributes:')
            for key, value in vars(self).items():
                print(key, '\t', value)
    
    def process(self): # handle bad data in packet directly & bufferSecs

        packet_processed = False # return value used to know if we should analyze() packet once exiting this function
        detached_packet = True # by default, we assume packet is detached. this means it will be processed without merging to a buffer
        packet_merged_to_buffer = False

        # do we want to load/reload Inventory yet - or just use what we've cached. we cache to save time, but reload periodically in case stationXML file changes
        update_now = True # mechanism to update/reload responses every response_update_interval seconds
        if not self.response_last_update_time or (obspy.UTCDateTime() < self.response_last_update_time + self.response_update_interval):
            update_now = False

        ### This section only used if using a buffer to stabilize detrending/filtering ###
        ### For applications where filtering not required, no buffer needed            ###
        # SCAFFOLD 20240815: added second test to next line to check packet can be merged with buffer
        
        if self.bufferSecs>0.0: # the intention is to use a buffer if this is >0 seconds

                
            ### Initialize or update the buffer by appending the new calibrated packet
            if isinstance(self.currentBuffer, Buffer):
                # clear procesing list of Buffer so it doesn't grow too large
                for tr in self.currentBuffer.raw:
                    tr.stats['processing']=[]
                packet_endtime = max([tr.stats.endtime for tr in self.currentPacket])
                buffer_starttime = min([tr.stats.starttime for tr in self.currentBuffer.raw])
                if (packet_endtime > buffer_starttime):
                    '''  
                    packet can be merged to buffer without gap at buffer start
                    such "attached packets" are processed with buffering
                    we don't care about gaps within the buffer - just interpolate
                    we replace any existing samples with samples from the new packet, 
                    but interpolate over any gaps, e.g. a missing packet 
                    '''
                    detached_packet = False
                    try:
                        self.currentBuffer.raw = (self.currentBuffer.raw + self.currentPacket).merge(method=1, fill_value='interpolate', interpolation_samples=0) # not sure we want to interpolate the raw buffer. maybe just the tmp buffer.
                    except Exception as e:
                        print('Failed to merge. Do we have different data types?')
                        print('BUFFER')
                        for tr in self.currentBuffer.raw:
                            print(f'id={tr.id}, type={tr.data.dtype}')
                        print('PACKET')
                        for tr in self.currentPacket:
                            print(f'id={tr.id}, type={tr.data.dtype}')
                        raise e
                    self.update_timings('buffer_update')
                else: # since detached_packet still set to True, this will be handled by logic below
                    pass
            else: # Create buffer from current packet
                self.currentBuffer = Buffer(self.currentPacket, self.filterdef, bufferSecs=self.bufferSecs) # create new buffer
                self.update_timings('buffer_setup')

        if detached_packet: # process current packet without buffering
            packet_processed = self.process_detached_packet(update_now)
        
        else: # process current packet with buffering
            if self.verbose:
                print('Packet attached to buffer')
            ### Perform detrending and filtering ONLY IF the calibrated data buffer is full ###
            ### If we have not appended enough packets yet to fill the calibrated buffer    ###
            ### detrending & filtering could produce odd results. So the tmp buffer, which  ### 
            ### is used for processing, is kept None until calibrated buffer is full        ###
            s = self.currentBuffer.raw[0].stats
            currentBufferSecs = s.endtime - s.starttime + s.delta
            if self.verbose and currentBufferSecs >= self.bufferSecs: # buffer full
                print('buffer is full')
            if currentBufferSecs > 0.0: # SCAFFOLD process regardless of buffer length
                self.currentBuffer.tmp = self.currentBuffer.raw.copy()
                buffer_filtered = self.currentBuffer.filter()
                if buffer_filtered:
                    self.update_timings('buffer_filtering')

                    # apply calibration correction to waveform data in the tmp buffer 
                    success = self.calibrate_Stream(self.currentBuffer.tmp, update=update_now)
                    self.update_timings('calibrate')
                    if not success:
                        IOError('Failed to calibrate buffer')

                    if self.verbose:
                        print('RAW BUFFER\n', self.currentBuffer.raw)

                    ### Update the current packet from the correct portion of the filtered buffer ###
                    self.currentPacket = self.currentBuffer.trim2packet(self.currentPacket)
                    self.update_timings('buffer_trim2packet') 
                    s = self.currentPacket[0].stats
                    stime = min([tr.stats.starttime for tr in self.currentPacket])
                    etime = max([tr.stats.endtime for tr in self.currentPacket])
                    if etime - stime > self.currentPacket[0].stats.delta: # otherwise we probably got no data
                        packet_processed = True
                
                else:
                    self.process_detached_packet(update_now)
                self.currentBuffer.trim2seconds() # trims calibrated data buffer back to self.bufferSecs (=self.CurrentBuffer.bufferSecs)
            elif self.verbose:
                print(f'buffer length now: {currentBufferSecs} seconds. Analysis will start when it reaches ({self.bufferSecs} seconds)')
                self.currentBuffer.print()
        return packet_processed

    def process_detached_packet(self, update_now):
        if self.verbose:
            print('Detached packet')
        self.currentPacket.detrend('constant')
        self.calibrate_Stream(self.currentPacket, update=update_now, pre_filt=None)
        self.update_timings('calibrate')
        return True

    def analyze(self):
        pass

    def update_timings(self, stringID):
        if self.benchmark:
            self.timingObj.update(stringID)
    
    def update_latency(self):
        packet_is_late = False
        if self.latency_on:
            packet_is_late = self.latencyObj.update(self.currentPacket)
            self.update_timings('updating_latency')
        return packet_is_late

    def calibrate_Stream(self, st, update=False, pre_filt=None):
        calibrated = False

        # get or update inventory
        if not self.inventory or update:
            try:
                #self.inventory = obspy.read_inventory(os.path.join(os.getenv('HOME'), 'pipeline', self.xmlfile), format='STATIONXML') #, level='response')
                self.inventory = obspy.read_inventory(self.xmlfile, format='STATIONXML') #, level='response')
            except:
                raise IOError(f'Could not read inventory {self.xmlfile} from current directory {os.getcwd()}')
            else:
                self.response_last_update_time = obspy.UTCDateTime()

        # attach response for each Trace in Stream        
        try:
            st.attach_response(self.inventory)
        except:
            print('Failed to attach response')

        # remove response, or calibrate waveform data in each Trace
        try:
            if self.remove_instrument_response: # full instrument response removal requested
                st.remove_response(pre_filt=pre_filt, output='ACC')
            else: # calibration correction only from Counts to m/s^2 requested
                for tr in st:
                    if 'response' in tr.stats:
                        gain = tr.stats.response.instrument_sensitivity.value
                        tr.data /= gain                
        except:
            print('Failed to remove response')
        else:
            calibrated = True

        return calibrated

    def updateCurrentPacket(self): 
        got_new_packet = False
        st = self.client.nextpacket2Stream(starttime=self.nextpacketstarttime, verbose=self.verbose) # starttime only used in datascope2obspy
        for tr in st: # merge interpolation can fail without recasting int64 to float
            tr.data = tr.data.astype(float)
        self.nextpacketstarttime = min([tr.stats.endtime for tr in st]) # update so next call to datascope2obspy will not repeat same time range
        if self.verbose:
            print(f'RAW_PACKET: seconds = {self.secondsPerPacket:.02f}, Traces = {len(st)}')
            print(f'Stream={st}')       

        # remove any Trace objects without valid data (just NaN or Inf or empty), and fill any remaining missing or Inf values with median (will not affect PGA, but could affect other measurement types)
        for tr in st:
            if not(np.any(np.isfinite(tr.data))):
                st.remove(tr)
            else:
                value = np.nanmedian(tr.data)
                tr.data = np.nan_to_num(tr.data, nan=value, posinf=value, neginf=value)                 

        if len(st)>0: 
            self.currentPacket = st
            got_new_packet = True
        self.update_timings('nextpacket2Stream')
        return got_new_packet
            
    def run(self):

        if self.verbose:
            print('Date: ', obspy.UTCDateTime().strftime('%Y-%m-%d'))
            print('Time now: ', obspy.UTCDateTime().strftime('%H:%M:%S'))
            print(f'Will attempt to load data from {self.starttime.strftime("%H:%M:%S")} to {self.endtime.strftime("%H:%M:%S")}')
            msg = f'Loading {self.duration} seconds of data for {self.station} {self.channel} from {self.datasource} using {self.api}'
            print(msg)  

        ############################# Loop over packets ###################
        self.nextpacketstarttime = self.starttime 
        while self.nextpacketstarttime < self.endtime:

            if self.verbose:
                print('\n')
            got_new_packet = False
            while not got_new_packet: # keep looping till the packet Stream is non-empty
                got_new_packet = self.updateCurrentPacket()
            
            '''
            We got a new packet. We'll update latency info, process, and analyze the packet.
            Note that if we are using a buffer (e.g. either bufferSecs was explicitly set to >0.0 s, or filterdef is set)
            then packet will only be analyzed once enough packets have been accumulated to fill the buffer. See self.process()
            '''
            self.npackets += 1
 
            self.update_timings('load_loop_update')
            packet_is_late = self.update_latency()
            if packet_is_late: # for example, if maximum_latency = 600, and latency of current packet exceeds that
                # we should have sent alarm when calling update_latency and now we skip to getting another packet
                continue
            
            packet_processed = self.process()
            self.update_timings('return_process')

            if packet_processed:
                self.analyze()
                self.update_timings('return_analyze')
            else:
                IOError('Failed to process (and analyze) packet!')
                #if self.mode == 'archive': # SCAFFOLD to get test alarm /test_alarm_datascope2obspy_202310181904 to work, which is stuck processing same time over and over as a packet has no length after processing
                #    self.nextpacketstarttime += self.secondsPerPacket
            if self.verbose:
                print(f'next packet start time = {self.nextpacketstarttime}')
        ########################### End loop over packets #################

    def report(self):
        if self.benchmark:
            self.timingObj.report(self.npackets)

        if self.latency_on and self.mode == 'realtime':
            self.latencyObj.report()
            titlestr = f"Data latency for {self.nslc} using {self.api}"
            outfile=os.path.join(self.outputdir,f'latency_{self.station}.png')
            self.latencyObj.plot(title=titlestr, outfile=outfile)

    def close(self): # close api client
        self.client.close()

################################################################################
class Buffer:    
    def __init__(self, stpacket, filterdef, bufferSecs=10.0): # a buffer is created from the first packet but for SlinkServer, also need to check NSLC and have one for each
        # pre-pad or trim to seconds
        self.raw = stpacket.copy() # a buffer Stream for unfiltered, but calibration corrected waveform data
        self.tmp = None # the buffer Stream we do any processing on
        self.bufferSecs = bufferSecs
        self.filterdef = filterdef

    def trim2seconds(self):
        ''' trim buffer to bufferSecs seconds to stop it growing too long and consuming unnecessary RAM '''
        etime = max([tr.stats.endtime for tr in self.raw])
        stime = min([tr.stats.starttime for tr in self.raw])
        if etime - self.bufferSecs > stime:
            self.raw.trim(starttime=etime-self.bufferSecs)

    def filter(self):
        buffer_filtered = False
        # replace any nan values
        #handle_bad_data(self.tmp, fill_value='mean') # remove any nan values, including trailing nans, before detrending?
    
        try:
            self.tmp.detrend('linear')
        except NotImplementedError as e: # may have multiple traces with same SEED id that cannot be merged
            print('Warning: failed to detrend buffer')
            return buffer_filtered

        # filter, if requested
        if self.filterdef:
            filterdef = self.filterdef

            # pad with reversed buffer - needed for tapering and/or two-way filtering
            for tr in self.tmp:
                tr.data = np.concatenate((tr.data, np.flip(tr.data)))

            # taper
            self.tmp.taper(0.25)

            # filter
            if filterdef['type']=='bandpass':
                self.tmp.filter(filterdef['type'],freqmin=filterdef['freq'][0], freqmax=filterdef['freq'][1],corners=filterdef['corners'], zerophase=filterdef['zerophase'])
            else:
                self.tmp.filter(filterdef['type'], freq=filterdef['freq'][0], corners=filterdef['corners'], zerophase=filterdef['zerophase'])

            # unpad the buffer
            for tr in self.tmp:
                N = int(tr.stats.npts/2)
                tr.data = tr.data[0:N]

        buffer_filtered = True
        return buffer_filtered

    def trim2packet(self, packet_st):
        """ Trims tmp buffer to same time range as current packet. Used to update current packet after filtering the buffer """
        stime = min([tr.stats.starttime for tr in packet_st])
        etime = max([tr.stats.endtime for tr in packet_st])       
        return self.tmp.copy().trim(starttime=stime, endtime=etime)
################################################################################
class timings():
    def __init__(self, tstart): #SCAFFOLD: added tstart
        self.timings = {}
        this_time = obspy.UTCDateTime()
        self.timings['initial_setup'] = this_time - tstart
        self.last_time = this_time
    
    def update(self, stringID):
        this_time = obspy.UTCDateTime()
        tdiff = this_time - self.last_time
        if stringID in self.timings.keys():
            self.timings[stringID] += tdiff
        else:
            self.timings[stringID] = tdiff
        self.last_time = this_time

    def report(self, npackets):
        print('\nSUMMARY:')
        print(f'# time windows = {npackets}')
        for k in self.timings.keys():
            if k == 'last_time':
                continue
            v = self.timings[k]
            print(f'Label {k} took {v:5.2f} seconds: average {v*1000/npackets:5.1f} milliseconds per time window')

################################################################################
class latency():
    ROWNUM = -1
    def __init__(self, station, seconds_to_keep=600, \
                 maximum_latency=60, email_list=[], outputdir='.', alarm_timeout=60):
        self.rownum = []
        self.seed_id = []
        self.time = []
        self.start = []
        self.end = []
        self.min_latency = []
        self.duration = []
        self.station = station
        self.seconds_to_keep = seconds_to_keep
        self.last_trimmed_time = obspy.UTCDateTime()
        self.maximum_latency = maximum_latency
        self.last_latency = maximum_latency * 10 # prevent alarm with first set of packets
        self.email_list = email_list
        self.outputdir = outputdir
        self.csvfile = os.path.join(self.outputdir,f'latency_{station}.csv')
        self.last_alarmtime = obspy.UTCDateTime(1900,1,1) # a dummy value
        self.alarm_timeout = alarm_timeout
        # start the output file
        row = 'rownum,seed_id,time,starttime,endtime,latency,duration\n'
        append_to_csvfile(self.csvfile, row)

    def update(self, st):
        packet_is_late = False
        alarm_seed_ids = []
        max_current_latency = 0.0
        now = obspy.UTCDateTime()

        for tr in st:
            self.ROWNUM += 1
            self.rownum.append(self.ROWNUM)        
            s = tr.stats
            this_latency = s.loadtime - s.endtime
            this_duration = s.endtime - s.starttime + s.delta
            max_current_latency = max([max_current_latency, this_latency])
            self.seed_id.append(tr.id)
            self.time.append(s.loadtime)
            self.start.append(s.starttime)
            self.end.append(s.endtime)
            self.min_latency.append(this_latency)
            self.duration.append(this_duration)
            row = f'{self.ROWNUM},{tr.id},{s.loadtime},{s.starttime},{s.endtime},{this_latency},{this_duration}' + '\n'
            append_to_csvfile(self.csvfile, row)

            # Latency alarm criteria
            if self.maximum_latency > 0: # maximum_latency must be a positive number, else disable alarms
                if this_latency > self.maximum_latency: # over the limit
                    packet_is_late = True
                    if this_latency > self.last_latency + 0.5: # latency must have increased over previous value - should eliminate startup latency too
                        alarm_seed_ids.append(tr.id)
                        
        # We still only send an alarm if we are beyond the latency_alarm_timeout period 
        if alarm_seed_ids:
            if now > self.last_alarmtime + self.alarm_timeout: # did we exceed latency criteria for any seed_id?
                self.send_alarm(alarm_seed_ids)
                self.last_alarmtime = now
        self.last_latency = max_current_latency

        # trim the object
        if obspy.UTCDateTime() > self.last_trimmed_time + self.seconds_to_keep:
            self.trim()
            trim_csvfile(self.csvfile)

        return packet_is_late 

    def plot(self, outfile='latency.png', seed_ids=None, load_csv=False, title=None):
        timecol = 'time'
        ycol = 'min_latency'
        if load_csv:
            df = pd.read_csv(self.csvfile)
            df['datetime'] = [obspy.UTCDateTime(tstr).datetime for tstr in df[timecol]]    
        else:
            self.trim() # trim so we always have a consistent 10-minute plot, or whatever seconds_to_keep is set to
            df = self.to_dataframe()
            df['datetime'] = [t.datetime for t in df[timecol]]
        seed_ids = df['seed_id'].unique()

        fig, ax = plt.subplots(1,1)
        cols = ['k', 'b', 'g']
        for index,seed_id in enumerate(seed_ids):
            thisdf = df[df.seed_id == seed_id]
            ymax = max([self.maximum_latency, thisdf[ycol].max()])
            ymin = min([self.maximum_latency, thisdf[ycol].min()]) 
            df2 = thisdf.copy()
            df2.reset_index(inplace=True)
            df2.plot(ax=ax, x='datetime', y=ycol, style='.-', label=seed_id[-1], \
                     title=f'Latency for {self.station}?', ylim=[ymin/1.5, ymax*1.5], logy=True, color=cols[index])
        ax.set_xlabel(f"Date/Time on {df.loc[0, 'datetime'].strftime('%Y/%m/%d')}") # getting a string here, probably when loading from file
        ax.set_ylabel('Latency (s)')
                
        handles, labels = ax.get_legend_handles_labels()
        handles.append(ax.axhline(y=self.maximum_latency, xmin=-1, xmax=1, color='r', linestyle='--', lw=2, label='max latency'))
        xlims = ax.get_xlim()
        ax.text((xlims[0]+xlims[1])/2, self.maximum_latency, 'alarm level', color='r', fontsize=12)
        plt.legend(handles=handles)
        plt.savefig(outfile)
        plt.close()

    def to_dataframe(self):
        df = pd.DataFrame()
        df['rownum'] = self.rownum
        df['seed_id'] = self.seed_id
        df['time'] = self.time
        df['start'] = self.start
        df['end'] = self.end
        df['min_latency'] = self.min_latency
        df['duration'] = self.duration
        return df

    def report(self):
        df = self.to_dataframe()
        print('Latency DataFrame:\n',df)
        print('Latency DataFrame stats:\n',df.describe())

    def trim(self):
        # find index N where self.time is within the last self.seconds_to_keep seconds
        N = next(x for x, val in enumerate(self.time) if val>self.time[-1]-self.seconds_to_keep)        
        self.rownum = self.rownum[N:]
        self.seed_id = self.seed_id[N:]
        self.time = self.time[N:]
        self.start = self.start[N:]
        self.end = self.end[N:]
        self.min_latency = self.min_latency[N:]
        self.duration = self.duration[N:]

    def load(self):
        df = pd.read_csv(self.csvfile)
        self.rownum = df['rownum']
        self.seed_id = df['seed_id']
        self.time = df['time']
        self.start = df['start']
        self.end = df['end']
        self.min_latency = df['min_latency']
        self.duration = df['duration']

    def send_alarm(self, seed_ids):
        now = obspy.UTCDateTime()
        station = seed_ids[0].split('.')[1]
        subject = f"Latency Alarm at {station} at {now}"
        body = f"Latency Alarm on {seed_ids} at {now.strftime('%Y-%m-%dT%H:%M:%S')}"
        pngfile = os.path.join(self.outputdir, f"latency_alarm_{self.station}_{now.strftime('%Y%m%d%H%M%S')}.png")
        self.plot(outfile=pngfile, load_csv=False)
        send_email_alarm(subject, body, self.email_list, pngfile=pngfile, verbose=True)    

################################################################################
###                            FUNCTIONS                                     ###
################################################################################
def send_email_alarm(subject, body, email_list, pngfile=None, verbose=True):
    sender = f'{UNAME}\@{HOSTNAME}.giseis.alaska.edu'
    cmd = f'echo "{body}" | rtmail -f {sender} -s "{subject}" '
    if pngfile:
        cmd += f' -a {pngfile} '
    recipients = email_list[0]
    for i in range(1, len(email_list)):
        recipients = f"-c {email_list[i]} " + recipients
    cmd += f' {recipients}'   
    if verbose: # for log file, or screen output
        print(f'cmd="{cmd}"')  
    subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True, encoding='UTF-8')

#######################################
def append_to_csvfile(csvfile, row, timeout=0.3):
    now = obspy.UTCDateTime()
    success = False
    while obspy.UTCDateTime() - now < timeout:
        try:
            with open(csvfile, 'a') as fptr:
                fcntl.flock(fptr, fcntl.LOCK_EX | fcntl.LOCK_NB) # lock the file
                fptr.write(row)
                fcntl.flock(fptr, fcntl.LOCK_UN)
                success = True
                break
        except Exception as e:
            print('Exception in append_to_csvfile\n',e)
            time.sleep(0.05)
    if not success:
        raise IOError(f'Terminating in append_to_csvfile function at {now} for {csvfile}') 
"""
def trim_csvfile(csvfile, seconds=100.0, timeout=0.3):
    # idea is just to keep up to one hour of rows in the CSV files, so they do not become too large
    now = obspy.UTCDateTime()
    success = False
    while obspy.UTCDateTime() - now < timeout:
        try:
            with open(csvfile, 'r') as fptr:
                fcntl.flock(fptr, fcntl.LOCK_EX | fcntl.LOCK_NB) # lock the file so nothing else messes with it

                # read CSV file and make a mask for last hour of data
                df = pd.read_csv(csvfile, index_col=[0])
                df['starttime'] = [obspy.UTCDateTime(tstr) for tstr in df['starttime']] 
                mask = (df['starttime']>obspy.UTCDateTime()-seconds) 

                # recreate CSV file from mask matching rows - the last hour
                dfnew = df.loc[mask]
                if len(dfnew)>0:
                    dfnew.to_csv(csvfile)
                fcntl.flock(fptr, fcntl.LOCK_UN)

                # save rows that do not match mask to a daily pickle file
                dfold = df.loc[~mask]
                if len(dfold)>0:
                    starttimeold = dfold.loc[0, 'starttime']
                    endtimeold = dfold.loc[-1, 'starttime']
                    thisdt = obspy.UTCDateTime(starttimeold.year, starttimeold.month, starttimeold.day)
                    while thisdt < endtimeold:
                        picklefile = csvfile.replace('.csv', f'_{thisdt.strftime("%Y%m%d")}.pkl')
                        thisdf = dfold.loc[(dfold['starttime']>=thisdt and df.old['starttime']<thisdt+1)]
                        if len(thisdf)>0:
                            if os.path.isfile(picklefile):
                                dfday = pd.read_pickle(picklefile)
                                dfday = pd.concat([dfday, thisdf])
                                dfday.to_pickle(picklefile)
                            else:
                                thisdf.to_pickle(picklefile)
                        thisdt += 1
                success=True
                break
        except Exception as e:
            print('Exception in latency/trim_csvfile\n',e)
            time.sleep(0.05) 
    if not success:
        raise IOError(f'Terminating in trim_csvfile function at {now} for {csvfile}') 
    """
    
def trim_csvfile(csvfile, seconds=None, timeout=0.1):
    if not seconds:
        return
    # idea is just to keep up to 10 minutes of rows in the CSV files, so they do not become too large
    numlinestokeep = int(seconds * 3) # assumes 3 channels and 1 second packets

    def wc_minus_l(fname):
        p = subprocess.Popen(['wc', '-l', fname], stdout=subprocess.PIPE, 
                                                stderr=subprocess.PIPE)
        result, err = p.communicate()
        if p.returncode != 0:
            raise IOError(err)
        return int(result.strip().split()[0])
    
    numlines=wc_minus_l(csvfile)
    if numlines <= numlinestokeep:
        return

    now = obspy.UTCDateTime()
    read=False
    lines=[]
    while obspy.UTCDateTime() - now < timeout and read==False:
        try:
            with open(csvfile, 'r') as fptr:
                fcntl.flock(fptr, fcntl.LOCK_EX | fcntl.LOCK_NB) # lock the file so nothing else messes with it

                # read all lines of file
                lines = fptr.readlines()
                read = True
        except Exception as e:
            print(f'Exception reading lines from {csvfile}: {e}')

    if len(lines)>numlinestokeep:
        written=False
        now = obspy.UTCDateTime()
        while obspy.UTCDateTime() - now < timeout and written==False:
            try:
                with open(csvfile, 'w') as fptr2:
                    fcntl.flock(fptr2, fcntl.LOCK_EX | fcntl.LOCK_NB) # lock the file so nothing else messes with it
                    fptr2.write(lines[0])
                    for line in lines[-numlinestokeep:]:
                        fptr2.write(line)
                    written=True
            except Exception as e:
                print(f'Exception writing lines to {csvfile}: {e}')

def get_params(argv):

    ###########################################################################
    # SETTING UP PARAMETERS FROM COMMAND LINE & PARAMETER FILE
    ###########################################################################

    parser = argparse.ArgumentParser(description='ingest waveform data packets')
    parser.add_argument('-b', '--benchmark', action='store_true', help='turn benchmarking on')
    parser.add_argument('-l', '--latency', action='store_true', dest="latency_on", help='turn latency tracking on')
    parser.add_argument('-v', '--verbose', action='count', default=0, help='turn verbose output on (-vv makes more verbose)')
    parser.add_argument('-p', '--inputfile', action='store', dest='inputfile', default=argv[0].replace('.py', '.yml'), help='YAML config file path/name')
    parser.add_argument('-s', '--starttime', action='store', help='UTC starttime')
    parser.add_argument('-e', '--endtime', action='store', help='UTC endtime' )  
    parser.add_argument('-n', '--nslc', action='store', help='net.sta.loc.chan to process')  
    parser.add_argument('-a', '--api', action='store', help='either datascope2obspy, orb2obspy, or slink2obspy')
    parser.add_argument('-o', '--outputdir', action='store', default=obspy.UTCDateTime().isoformat(), dest='outputdir', help='where to save output files') 
    command_line_dict = vars(parser.parse_args(sys.argv[1:]))

    ####################################
    ### Get params from parameter file
    ####################################
    with open(command_line_dict["inputfile"], 'r') as yml:
        params = yaml.safe_load(yml) 

    ################################################
    ### Get params from command line
    ### These will override same from parameter file
    ################################################
    for k, v in command_line_dict.items():
        if v is not None:
            params[k] = v

    ################################################
    ### Make sure times are type obspy.UTCDateTime
    ### and that we have consistent times, duration, mode
    ################################################

    def round_utcdatetime(udt): # round down to nearest second
        if isinstance(udt,str):
            udt = obspy.UTCDateTime(udt)
        return obspy.UTCDateTime(round(udt.timestamp-0.5)) # 0.5 second subtraction makes this behave like a floor function - rounds down

    params['starttime'] = round_utcdatetime(params['starttime']) if 'starttime' in params else round_utcdatetime(obspy.UTCDateTime()) # just rounds to the nearest second
    params['endtime'] = round_utcdatetime(params['endtime']) if 'endtime' in params else obspy.UTCDateTime(2099,12,31)
    if 'duration' in params and params['duration']>0.0:
        params['endtime'] = params['starttime'] + params['duration']
    if params['endtime']<obspy.UTCDateTime(): # if endtime is in past, turn on archive mode
        params['mode']='archive'
    else:
        params['mode']='realtime'
    if params['mode']=='archive': # turn off latency tracking if in archive mode
        params['latency_on'] = False

    # summarize
    if command_line_dict["verbose"]:
        print('Parameters from command line & parameter file')
        for key, value in params.items():
            print(key,'\t',value)
        print('')

    return params

def main(argv):

    params = get_params(argv)

    ###########################################################################
    # THIS IS WHERE THE WORK GETS DONE
    ###########################################################################

    datahandler = RealTimeDataClient(params)
    datahandler.run()
    datahandler.close()

    ###########################################################################
    # THIS IS ALL ABOUT REPORTING WHAT HAPPENED
    ########################################################################### 
    datahandler.report()


# THIS GETS CALLED WHEN PROGRAM RUN FROM COMMAND LINE        
if __name__ == "__main__":
    main(sys.argv) 
