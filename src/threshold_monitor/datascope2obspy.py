#!/usr/bin/env python
"""
File: datascope2obspy.py
Author: Glenn Thompson
Date: 2024-06-14
Description: This library provides a consistent data ingestion interface with slink2obspy and orb2obspy for fetching the latest waveform data packet 
             from (in this case) a Datascope wfdisc table. In this case, the term 'packet' is used loosely: we are just getting the latest chunk of 
             waveform data since the previous chunk of data was fetched. Each packet is fetched as an ObsPy Stream object and contains 1 or many Trace objects.

             DatascopeClient (a new class, defined below) accomplishes this by wrapping wf2obspy's get_waveforms() function, which does the heavy lifting..
"""

import sys
from obspy import UTCDateTime
from os import path
import numpy as np

thisdir = path.realpath(path.dirname(__file__))
pymodsdir = path.join(thisdir.split('rt')[0], 'pymodules')
sys.path.append(pymodsdir)
import wf2obspy

class DatascopeClient(object):

    DEFAULT_DB = "/aec/db/waveforms/waveforms"

    def __init__(self, dbname, secondsPerPacket=1.0, starttime=None, mode='realtime'): 
        """ 
        initializes a DatascopeClient object with a single attribute - 

        Parameters:
            dbname (str, optional): a database name. If blank "", defaults to AEC waveforms db
            secondsPerPacket (float, optional): limits the maximum 'packet' to the last secondsPerPacket seconds (default: 1.0). But starttime can be shifted with dbstarttime parameter.
            starttime (UTCDateTime, optional): Start the packet at this time, and end secondsPerPacket later, or current time (whichever is earlier).

        Returns:
            an ObsPy Stream object containing 1 or many Trace objects, corresponding to the data packet
            
        """
        self.dbname = dbname
        self.secondsPerPacket = secondsPerPacket

        if starttime:
            self.starttime = starttime
        else:
            self.starttime = UTCDateTime()

        self.mode = mode

    def select_stream(self, network, station, location, channel):
        """
        Sets the streams (SEED ids) that will be allowed from the Datascope wfdisc table

        Parameters:
            network (str): Select one or more network codes. Can be SEED network codes or data center defined codes. Multiple codes are comma-separated (e.g. "IU,TA"). Wildcards are allowed.
            station (str): Select one or more SEED station codes. Multiple codes are comma-separated (e.g. "ANMO,PFO"). Wildcards are allowed.
            location (str): Select one or more SEED location identifiers. Multiple identifiers are comma-separated (e.g. "00,01"). Wildcards are allowed.
            channel (str): Select one or more SEED channel codes. Multiple codes are comma-separated (e.g. "BHZ,HHZ").

        Returns:
            None

        """
        self.network = network
        self.station = station
        self.location = location
        self.channel = channel

    def nextpacket2Stream(self, starttime=None, verbose=False): 
        """
        Fetches the next "packet" from a Datascope wfdisc table via wf2obspy.get_waveforms(), and returns it as an ObsPy Stream

        Parameters:
            secondsPerPacket (float, optional): limits the maximum 'packet' to the last secondsPerPacket seconds (default: 1.0). But starttime can be shifted with starttime parameter.
            starttime (UTCDateTime, optional): Start the packet at this time, and end secondsPerPacket later, or current time (whichever is earlier).

        Returns:
            an ObsPy Stream object containing 1 or many Trace objects, corresponding to the data packet
            
        """
        NOW = UTCDateTime()
        MINIMUM_PACKET_SECS = self.secondsPerPacket * 0.99 # if in realtime mode, at least one Trace in Stream must be this long
        MAX_LATENCY = 60.0
        if starttime:
            endtime = min([NOW, starttime + self.secondsPerPacket])
        else:
            starttime = NOW - self.secondsPerPacket
            endtime = NOW
        
        max_nsecs = 0.0 # total seconds of data in the "packet"
        got_data = False
        
        while not got_data:
            if self.dbname == 'default' and self.mode =='archive':
                st = wf2obspy.get_waveforms(self.network, self.station, self.location, self.channel, starttime, endtime)
            else: # SCAFFOLD> was getting nothing back so removing dbname from call
                st = wf2obspy.get_waveforms(self.network, self.station, self.location, self.channel, starttime, endtime ) #, dbname=self.dbname)
            if verbose:
                print('wf2obspy returned ',st)
            # returns nan in place of missing data. so remove trailing nan.
            NOW = UTCDateTime()
            for tr in st:
                tr.stats['loadtime']=NOW
                
                if not np.any(np.isfinite(tr.data)): 
                    # remove any Trace objects that contain only nans. needed because wf2obspy returns nans for missing data
                    if verbose:
                        print(f'Removing {tr.id} from Stream: no finite values')
                    st.remove(tr) 
                    continue
                
                # we also have to deal with case where we have partial data, but then wf2obspy fills the rest of the packet with nans
                if self.mode == 'realtime':
                    y = np.nan_to_num(tr.data, nan=0.0, posinf=0.0, neginf=0.0)
                    y = np.trim_zeros(y, trim='b') # trim trailing zeros
                    tr.data = tr.data[0:len(y)] # we just take first len(y) samples of tr.data since rest are nans


            if len(st)>0:
                if self.mode == 'archive': # no new data coming, so return
                    got_data = True
                else: # realtime mode
                    max_nsecs = max([(tr.stats.npts+1) * tr.stats.delta for tr in st])
                    if max_nsecs >= MINIMUM_PACKET_SECS:
                        got_data = True
                    else:
                        if verbose:
                            print(f'datascope2obspy still only got {max_nsecs} seconds of data')
            elif self.mode == 'realtime':
                # we are in realtime mode, and got no (non-nan) data. so we loop again.
                continue
            else:
                # we are in archive mode, and got no (non-nan) data. looping again is pointless, as nothing new coming. so increment time by one packet length.
                starttime += self.secondsPerPacket
                endtime += self.secondsPerPacket

        return st

    def close(self):
        """ 
        Added for consistency. 
        Does nothing because wf2obspy.get_waveforms opens and closes database
        with each read
        """
        pass
