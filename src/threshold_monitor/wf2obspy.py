# Created 2023-03-29 by Luke Underwood and Gabe Paris
# based heavily on db2stream from LT_gaps.py written by Steve Holtkamp
# module for AEC researchers to import waveform data from local servers to an obspy stream

'''
DESCRIPTION:

    wf2obspy is a module containing a single function, get_waveforms. This function accesses seismic waveform data
    via nfs mounts from AEC's server Helium and a diskstation, taking it out of the antelope datascope database in which
    it is normally stored and making it accessible to the much more user-friendly, pythonic, and feature-rich obspy
    toolset. This function has been modeled after the behavior of obspy's get_waveforms (documentation can be found here:
    https://docs.obspy.org/packages/autogen/obspy.clients.fdsn.client.Client.get_waveforms.html), but instead of downloading
    the data from the fdsn client, it imports the data from local servers at the GI.

USAGE:

    To use this module, place it in the same directory as the client code or configure a PYTHONPATH environment variable
    to make it accessible from elsewhere. Then, it can be imported and used in either of these two ways:

    import wf2obspy
    wf2obspy.get_waveforms()
    
    from wf2obspy import get_waveforms
    get_waveforms()

INPUTS:

    get_waveforms takes six parameters, and none of them are optional. network, station, location, and channel can all
    be passed either a string or a list to specify one or more of each parameter. Using network as an example, all of the 
    following formats are accepted for all of these parameters: "AK", "AK, AV", "AK,AV", ["AK"], ["AK", "AV"]. Additionally, 
    the UNIX-style wildcards * and ? can be used for these four parameters, where * matches any string and ? matches any 
    one character.

    network:
        A network code or list of network codes. Common examples are AK for AEC sites, CN for Canadian sites, AV for AVO
        sites, or IM for military sites.

    station:
        A station code or list of station codes, generally 3-5 characters in length. Some examples are COLA, POKR, or BAT.
        AEC's network map can be found here for more stations and their network codes: https://earthquake.alaska.edu/network

    location:
        A loc code or location code which can be used to differentiate between two of the same type of sensor at a 
        given site. Generally it is a number, two characters long such as 00 or 01. For most purposes, the * wildcard can be
        passed for location to just get all available data.

    channel:
        A sensor channel or list of channels which generally indicates what type of sensor and/or what axis on the sensor
        the waveform is from. Use of wildcards is helpful for this parameter as well, as instead of listing all three axes
        for a sensor (such as "BHE, BHN, BHZ") you could specify "BH?".

    starttime:
        This should be an obspy UTCDateTime object specifying the desired start time of the waveforms.
        (docs here: https://docs.obspy.org/packages/autogen/obspy.core.utcdatetime.UTCDateTime.html#obspy.core.utcdatetime.UTCDateTime)

    endtime:
        This should be an obspy UTCDateTime object specifying the desired end time of the waveforms.

OUTPUTS:

    get_waveforms returns an obspy Stream object (docs here: https://docs.obspy.org/packages/autogen/obspy.core.stream.Stream.html)
    containing some number of obspy traces (docs here: 
    https://docs.obspy.org/packages/autogen/obspy.core.trace.Trace.html#obspy.core.trace.Trace) determined by the inputs and the 
    data availability. All combinations of the provided networks, stations, locations, and channels will be attempted, and a 
    trace will be present in the returned Stream for each combination for which there was waveform data in the database.

SYSTEM REQUIREMENTS:

    The system running the calling code must have antelope's software suite installed. At the time of writing this module,
    antelope 5.12 was being used, and compatibility with any past or future versions cannot be guaranteed. 

    The system must have the obspy and numpy packages available.
    
    The system must also have the appropriate nfs mounts from AEC's servers, which will make waveform data available. This can 
    be verified by running "dbe /aec/db/waveforms/YYYY_MM/waveforms_YYYY_MM_DD.wfdisc", where YYYY MM and DD are replaced with 
    appropriate date information for the waveforms being acquired, then clicking graphics->waveforms and zooming in with 
    shift-click until waveforms are visible. If you encounter an error, or lack of waveforms at any point in that process, 
    contact the AEC systems team for assistance.

    The system must also of course have python3 installed.

EXAMPLES:

    s1 = UTCDateTime("2022-10-01 23:59:00")
    duration = 180

     st = wf2obspy.get_waveforms("IM", "BC01,BC02,BC03,BC04,BC05", "*", "*", s1, s1+duration, dbname)

    st = wf2obspy.get_waveforms("IM", "BC01,BC02,BC03,BC04,BC05", "*", "*", s1, s1+duration)

    st = wf2obspy.get_waveforms("IM", "BC*", "*", "*", s1, s1+duration)

    st = wf2obspy.get_waveforms("IM, AV, AK", "BC*, IL*, COLD", "*", "*Z", s1, s1+duration)

    st = wf2obspy.get_waveforms("*", ["BAE", "BAW", "PS11", "PS12", "VMT"], "*", "LHZ", s1, s1+duration)

    st = wf2obspy.get_waveforms("AK", "MCAR,PTPK,BARN,BAL", "*", "BHZ", s1, s1+duration)

    st = wf2obspy.get_waveforms("AK", ["MCAR","PTPK","BARN","BAL"], "*", "BHZ", s1, s1+duration)]
'''

import os
import sys

import signal

# GT 20240730: The signal.signal line comes from the Antelope build process, but is superfluous and it 
# causes wf2obspy to crash when called within a subprocess, so we comment it out
#signal.signal(signal.SIGINT, signal.SIG_DFL)

sys.path.append(os.environ['ANTELOPE'] + "/data/python")

import antelope.datascope as ds
from obspy import Stream, Trace
import numpy as np
import numpy.ma as ma
import math
import re


# inputs should be station, loc_code, channel, start time, and end time
# accepts * and ? wildcards
# returns obspy stream object with all relevant traces
def get_waveforms(network, station, location, channel, starttime, endtime, dbname=None):
    defaultdb = False 
    
    if(dbname is None):
        defaultdb = True
    # functions placed inside of get_waveforms because they should not be exposed as a public interface for this module

    # Code that actually clears a trace object from memory, because ds.free() doesn't work
    def free_tr(tr):
        tr.record = ds.dbALL
        tr.table = ds.dbALL
        tr.trfree()

    # handles input given as a single string, translating into list format
    def interpret_input(input):
        if type(input) == str:
            # turn it into a list, dividing on commas
            input = input.split(',')

            # remove any whitespace
            for i, string in enumerate(input):
                input[i] = string.strip()

        return input

    # translates wildcards into antelope's atypical format
    def replace_wildcard(input):
        input = input.replace('*', '.*')
        input = input.replace('?', '.')
        return input

    # confirms if the db is supposed to be the default or a custom one
    def get_db_name(time, dbname, defaultdb):
        ym = time.strftime('%Y_%m')
        ymd = ym + time.strftime('_%d')
        
        if(defaultdb):
            dbname = f'/aec/db/waveforms/{ym}/waveforms_{ymd}'

        return dbname
    # opens the database and returns a join of wfdisc and snetsta tables
    def open_db(time, dbname):

        db_name = get_db_name(time, dbname, defaultdb)
        #db_nme = f'/aec/db/waveforms/{ym}/waveforms_{ymd}'
        try:
            database = ds.dbopen(db_name, 'r')
            wfdisc = database.lookup(table='wfdisc')
            wfdisc = wfdisc.join("snetsta")
        except Exception as e:
            print("Problem loading the database [%s] for processing!" % db_name)
            raise e
        return wfdisc

    if starttime >= endtime:
        raise ValueError(f"Invalid times. The first time ({str(starttime)}) must be before the second ({str(endtime)})")

    # empty Stream object for result
    st = Stream()
    # used to validate traces. chanids[i] corresponds to st[i]
    stachans = []
    
    dbname = get_db_name(starttime, dbname, defaultdb)

    # create a list of databases spanning the full date range
    databases = [open_db(starttime, dbname)]
    curr_day = starttime
    
    if(defaultdb):
        
        while(curr_day.strftime("%D") != endtime.strftime("%D")):
            curr_day += 60*60*24
            databases.append(open_db(curr_day, dbname))
    # handle input
    network = interpret_input(network)
    station = interpret_input(station)
    location = interpret_input(location)
    channel = interpret_input(channel)
    


    curr_day = starttime
    # iterate over all days in databases array
    for wfdisc in databases:
        
        # get date strings formatted for trload
        e1 = curr_day.timestamp
        if curr_day.strftime("%D") != endtime.strftime("%D") and defaultdb:
            e2 = curr_day.replace(hour=23, minute=59, second=59, microsecond=980000).timestamp
        else:
            e2 = endtime.timestamp

        # iterate over all net-sta-loc-chan combos
        for n in network:
            for s in station:
                for l in location:
                    for c in channel:
                        
                        if e1 == e2: # trload_css does not behave as expected when this is the case
                            continue

                        net = replace_wildcard(n)
                        sta = replace_wildcard(s)
                        chan = replace_wildcard(c)
                        loc = replace_wildcard(l)

                        # join channel and loc_code to match antelope format, handling wildcards appropriately
                        chan_str = chan
                        if loc == '' or loc == '.*':
                            chan_str += '.*'
                        else:
                            chan_str += "_" + loc

                        # string to subset for current net-sta-chan-loc combo
                        subset_str = f"snet =~ /{net}/ && sta =~ /{sta}/ && chan =~ /{chan_str}/"

                        # create an empty datascope trace
                        tr = ds.dbinvalid()

                        # subset to current net-sta-chan-loc
                        with ds.freeing(wfdisc.subset(subset_str)) as db:

                            # load the waveforms
                            try:
                                tr = db.trload_css(e1, e2)
                            except:
                                # if a trace matching the current net/sta/chan/loc combo exists, add masked values to 
                                # represent the missing data
                                for trace in st:
                                    trace_info = (trace.stats.network + trace.stats.station + 
                                                trace.stats.channel + trace.stats.location)
                                    if re.fullmatch(net+sta+chan+loc, trace_info):
                                        gap = e2 - e1
                                        gap_fill = np.full(math.floor(gap * trace.stats.sampling_rate), np.nan)
                                        gap_masked = ma.masked_invalid(gap_fill)
                                        trace.data = np.concatenate((trace.data, gap_masked))
                                
                                # no further work needs to be done, so skip the rest of the loop body
                                continue
                            
                            # Iterate over the trace object
                            i = 0
                            for t in tr.iter_record():
                                
                                # get metadata from trace object
                                nsamp, samprate = t.getv('nsamp', 'samprate')
                                sta, chan = t.getv('sta', 'chan')
                                trace_start = t.getv('time')[0]

                                # get the real network code
                                with ds.freeing(db.subset(f"sta == '{sta}' && chan == '{chan}'")) as net_subset:
                                    net_subset.record = 0
                                    net = net_subset.getv('snet')[0]

                                # parse antelope chan_loc format
                                chan_split = chan.split('_')
                                chan = chan_split[0]
                                loc = chan_split[1] if len(chan_split) > 1 else ''
                                stachan = (sta, chan)
                                
                                # get the pre-existing trace from stream object if it exists, otherwise create a new trace
                                # (the trace would already exist if there are multiple dbs in databases)
                                if stachan not in stachans:
                                    tr0 = Trace()
                                    tr0.stats.network = net
                                    tr0.stats.station = sta
                                    tr0.stats.channel = chan
                                    tr0.stats.location = loc
                                    tr0.stats.sampling_rate = samprate
                                    tr0.stats.npts += nsamp
                                    tr0.stats.starttime = starttime
                                else:
                                    ind = stachans.index(stachan)
                                    tr0 = st[ind]
                                    if trace_start < math.floor((tr0.stats.starttime + (tr0.stats.npts / tr0.stats.sampling_rate)).timestamp):
                                        raise RuntimeError(f"There are duplicate waveforms for {net} {sta} {chan} {loc} {curr_day.strftime('%D')}")

                                d = np.array(t.trdata()) # get the actual data
                                d[abs(d)>=1e+30] = np.nan # set any gaps in the data to nan

                                # add additional nans for gaps not included in the data
                                # gap at start
                                if len(tr0.data) == 0: # where this is the start of the data in this trace
                                    gap = trace_start - e1
                                else:   # where there is already data in the trace
                                    gap = trace_start - (tr0.stats.starttime + (tr0.stats.npts / tr0.stats.sampling_rate)).timestamp
                                if gap >= (1/samprate):
                                    gap_fill = np.full(math.floor(gap * samprate), np.nan)
                                    d = np.concatenate((gap_fill, d))
                                # gap at end
                                gap = endtime.timestamp - t.getv('endtime')[0]
                                if e2 == endtime.timestamp and gap >= (1/samprate) and tr.record_count - 1 == i:
                                    gap_fill = np.full(math.floor(gap * samprate), np.nan)
                                    d = np.concatenate((d, gap_fill))

                                # mask gaps
                                d_masked = ma.masked_invalid(d)

                                # Populate the trace object
                                tr0.data = np.concatenate((tr0.data, d_masked))

                                # add the trace to the stream if there is data and it is not already in the stream
                                if len(tr0.data) > 0 and curr_day == starttime and stachan not in stachans:
                                    st.append(tr0)
                                    stachans.append(stachan)

                                i += 1
                            free_tr(tr)
        
        # advance by one day, and set time to 00:00:00
        if(defaultdb):
            curr_day += 60*60*24
            curr_day = curr_day.replace(hour=0, minute=0, second=0)
        else:
            curr_day += endtime - starttime
    
    # Clean-up
    for database in databases:
        database.table = ds.dbALL
        database.close()
    return st.sort()
