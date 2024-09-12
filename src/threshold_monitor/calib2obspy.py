#!/usr/bin/env python
"""
File: calib2obspy.py
Author: Glenn Thompson
Date: 2024-06-14
Description: This library contains 3 functions which, together, enable real-time data to be corrected using the calib value in the 
AEC master_stations calibration table. Optionally, another Datascope database, or a wfdisc table can be used. 
"""
import antelope.datascope as ds # for calib

def get_stations(seed_ids, dbname=None, dbtablename='calibration', time=None):
    """
    Fetches a response dict containing the most recent calibration information for each seed_id

    Parameters:
        seed_ids (list): a list of SEED ids (e.g., ['AK.PTPK..BHZ', 'AK.PS01..HNZ']
        dbname (str, optional): the path to a Datascope database. Defaults to AEC master_station db.
        dbtablename(str, optional): the name of the CSS3.1 table to use. defaults to 'calibration', but could also be 'wfdisc'

    Returns:
        A dict of response dicts.
      
    """   
    response_dicts = {}
    if not dbname: # use defaults    
        if dbtablename=='calibration':
            dbname = '/aec/db/stations/master_stations'
        elif dbtablename=='wfdisc':
            dbname = '/aec/db/waveforms/waveforms'
    for id in seed_ids:
        network, station, location, channel = id.split('.')
        with ds.closing(ds.dbopen(dbname, 'r')) as db:
            dbtable = db.lookup(table=dbtablename)
            response_dict = {}
            if time:
                sub_str =f"sta=~/{station}/ && chan=~/{channel}/ && time<={time.timestamp}"
            else:
                sub_str =f"sta=~/{station}/ && chan=~/{channel}/"
            dbview = dbtable.subset(sub_str)
            with ds.freeing(dbview):
                N = dbview.record_count
                print(f'Found {N} matching calibration table records for {sub_str}')
                if N==0:
                    raise LookupError(f'No matching calibration records found for {sub_str}')
                for rec in dbview.iter_record(N-1): # should just grab the most recent row. 
                    calib, calper, samprate, segtype = rec.getv('calib', 'calper', 'samprate', 'segtype')
                    if calper==-1:
                        calper=1.0
                    units = '?'
                    if segtype=='V':
                        units = 'nm/s'
                    elif segtype=='A':
                        units = 'nm/s**2'
                    if dbtablename=='calibration':
                        units = rec.getv('units')[0]
                    if 'nm' in units:
                        calib = calib / 1e9
                        units = units.replace('nm', 'm')
                response_dict = {'calib':calib, 'calper':calper, 'samprate':samprate, 'segtype':segtype, 'units':units}
            response_dicts[id]=response_dict
    return response_dicts

def attach_response(st, response_dicts, overwrite=False): 
    """
    Attaches a response dict containing calibration information to each Trace in a Stream

    Parameters:
        st (ObsPy Stream): the Stream object
        response_dicts (dict): a dict of response dicts from get_stations()

    Returns:
        None. The input Stream is updated inplace.  
      
    """
    
    seed_ids = [tr.id for tr in st]

    # Check to only attach responses for Trace object's that do not already have corrected units, and do not already have a response attached
    for tr in st:
        if 'units' in tr.stats and tr.stats.units!='Counts':
            # calib already applied       
                seed_ids.remove(tr.id)
                continue
        if not overwrite:
            if 'response' in tr.stats:
                # calib already attached
                seed_ids.remove(tr.id)
                continue

    # attach the response dicts to each Trace in the Stream
    for tr in st:
        if tr.id in response_dicts.keys():
            tr.stats['response'] = response_dicts[tr.id]
            tr.stats['units'] = 'Counts'


def remove_response(st, pre_filt=None):
    """
    Applies calibration data from a response dict to each corresponding Trace in a Stream

    Parameters:
        st (ObsPy Stream): the Stream object
        pre_filt (dict, optional): a dictionary containing filter parameters, e.g. pre_filt={'type':'bandpass', 'freq':[0.5, 20.0], 'corners':2}

    Returns:
        None. The input Stream is updated inplace.  
      
    """

    if pre_filt:
        if pre_filt['type']=='bandpass':
            st.filter(pre_filt['type'],freqmin=pre_filt['freq'][0], freqmax=pre_filt['freq'][1],corners=pre_filt['corners'])
        else:
            st.filter(pre_filt['type'],freq=pre_filt['freq'],corners=pre_filt['corners'])
    for tr in st:
        if 'response' in tr.stats and tr.stats['units']=='Counts':
            tr.data = tr.data * tr.stats.response['calib']
