#!/usr/bin/env python
"""
File: orb2obspy.py
Author: Glenn Thompson
Date: 2024-06-14
Description: This library provides a consistent data ingestion interface with slink2obspy and datascope2obspy for fetching the latest waveform data packet 
             from (in this case) a Orbserver, as an ObsPy Stream object. Each packet contains (multiplexed) waveform data for 1 or many SEED ids (net.sta.loc.chan)

             OrbserverClient (a new class, defined below) accomplishes this by subclassing and expanding Antelope's antelope.orb class

Inspired by:
- Luke Underwood's & Gabe Paris's wf2obspy.py: https://github.com/akquake/antelope/blob/orbtm_simulation/bin/pymodules/wf2obspy.py
- Nick Alexeev's orb_reader.py: https://github.com/akquake/data-visuals/blob/abd425cc7dc211c5d595da9ecd1da47e1cb43205/orb_broadcast/orb_reader.py#L6

Caveats:
- Only tested on a single NSLC at a time. Testing/Modification needed to work with multiple NSLCs.
- AK_PS??_HN?/GENC packets contain a single NSLC, but multiple NSLC's share same pkt_time. 
  So maybe align by packet time into a Stream before returning the packet stream to data_ingestion.py?

"""
from numpy import array
from obspy import Stream, Trace, UTCDateTime

from antelope.orb import Orb, OrbIncompleteException, OrbAfterError, OrbResurrectError, ORBNEXT 
from antelope.Pkt import Packet

import signal

class OrbserverClient(Orb):

    DEFAULT_ORB = "137.229.32.211:6520"

    def __init__(self, orbname, starttime=None, secondsPerPacket=1.0, timeoutsecs=-1, grouppackets=True, nslc='*.*.*.*', *args, **kwargs): 
        if orbname == 'default':
            orbname = self.DEFAULT_ORB
        try:
            print(f'Initiating orbserver client for {nslc}')
            super().__init__(orbname, *args, **kwargs) # default keyword args are: permissions=’r’, select=None, reject=None, exhume=None, auto_bury=True, bury_interval=10. no args.
            print('Initiated')
        except Exception as e:
            print(f'Got following error while trying to establish orbserver client for {nslc}: {e}')
        try:
            print(f'Initiating orbserver client connection for {nslc}')
            self.connect()
            print('Connected')
        except Exception as e:
            print(f'Got following error while trying to establish orbserver client connection for {nslc}: {e}')

        self.nslc = nslc
        if starttime:
            self.move_pointer(starttime)
        self.last_packet_stream = None
        self.secondsPerPacket = secondsPerPacket
        #self.timeoutsecs = timeoutsecs
        self.starttime = starttime
        self.grouppackets = grouppackets
        self.last_packet_id = None
        

    def select_stream(self, network='AK', station='*', location=None, channel=None):
        """ 
        Selects the orb packet stream types that will be allowed from the orbserver

        Parameters:
            network (str): Select one or more network codes. Can be SEED network codes or data center defined codes. Multiple codes are comma-separated (e.g. "IU,TA"). Wildcards are allowed.
            station (str): Select one or more SEED station codes. Multiple codes are comma-separated (e.g. "ANMO,PFO"). Wildcards are allowed.
            location (str): Select one or more SEED location identifiers. Multiple identifiers are comma-separated (e.g. "00,01"). Wildcards are allowed.
            channel (str): Select one or more SEED channel codes. Multiple codes are comma-separated (e.g. "BHZ,HHZ").

        Returns:
            None 
        """
        if channel:
            if network=='HT': # packet pattern of 'HT_10627_HNZ/GENC/Q8' is for Q8 that Nate set up 
                selectexpr = f'{network}_{station}_{channel}/GENC/Q8' 
            else:
                selectexpr = f'{network}_{station}_{channel}/GENC' # this style works for AK.PS??..HN?, but each packet contains only one NSLC
        else:
            selectexpr = f'{network}_{station}/GENC/*' # this style works for AK.PTPK..BHZ
        selectexpr = replace_wildcard(selectexpr)
        self.select(selectexpr)
        self.selectexpr = selectexpr
        self.network = network
        self.station = station
        self.location = location
        self.channel = channel
        print(f'Selecting packets matching: {selectexpr}')
        
    def move_pointer(self, starttime):
            """ Attempts to move the pointer to the starttime given (a UTCDateTime). """
            start_epoch = starttime.timestamp
            try:
                self.after(start_epoch)
            except OrbAfterError:
                print(f'OrbAfterError: Cannot move orb pointer to {start_epoch}: Requested: {starttime}, Time Now: {UTCDateTime()}')    
                #return 1
            else:
                print(f'moved pointer for {self.nslc}')
                #return 0

    def nextpacket(self):
        got_packet = False
        while not got_packet:
            try:
                (_pkt_id, srcname, pkt_time, pkt_data) = self.reap()
            except Exception as e:
                print(f'nextpacket: Exception with orbreap: {e}')
                continue
            else:
                #if pkt_time >= self.starttime.timestamp:
                packet = Packet(srcname=srcname, time=pkt_time, packet=pkt_data)
                self.last_packet_id = _pkt_id
                got_packet = True
        return packet

    @staticmethod
    def packet2stream(packet, allowed_channels='*'):
        """ converts a Orbserver packet into an ObsPy Stream containing 1 or many Trace objectsd """       
        st = Stream()
        for pktchannel_object in packet.channels: # object of class antelope.Pkt.PktChannel()
            channel_name = pktchannel_object.chan
            start_time = pktchannel_object.time # epoch time

            if not allowed_channels == '*' and not channel_name in allowed_channels:
                #print('not allowed - skipping channel')
                continue
            tr = Trace()
            tr.data = array(pktchannel_object.data)
            tr.stats.starttime = UTCDateTime(start_time)
            tr.stats.network = pktchannel_object.net
            tr.stats.station = pktchannel_object.sta
            tr.stats.location = pktchannel_object.loc
            tr.stats.channel = pktchannel_object.chan
            tr.stats.sampling_rate = pktchannel_object.samprate
            tr.stats['loadtime'] = UTCDateTime()
            st.append(tr)
        #print(f'orb packet: {st}')
        return st

    def nextpacket2Stream(self, starttime=None, verbose=False):
        """
        Fetches the next packet from an Orbserver, and returns it as an ObsPy Stream

        Parameters:
            starttime (ObsPy UTCDateTime): ignored

        Returns:
            an ObsPy Stream object containing 1 or many Trace objects, corresponding to the data packet
            
        """      
        if starttime: # no longer supported as it was causing programs to miss packets
            pass 

        """
        We want each "packet" returned to data_ingestion.py to contain data for all channels we are trying to collect, as processing 33 Trace objects in a Stream is much faster than processing 33 Stream objects, each containg one Trace object
        This is already the case for multiplexed packets, which I believe contain the code "MGENC" as opposed to just "GENC"
        """
        if 'MGENC' in self.selectexpr or not self.grouppackets:
            if verbose:
                print('SINGLE PACKET MODE')
            packet = self.nextpacket()
            st = OrbserverClient.packet2stream(packet, allowed_channels='*')
        else:
            if verbose:
                print('GROUPED PACKET MODE')
            st = self.group_packets_by_time(verbose=verbose)
        return st
    
    def group_packets_by_time(self, verbose=False):
        """
        added this upon expansion from 1 to 33 channels. idea is to group packets from all 33 channels that share a common start time into a single Stream object, 
        so we only have one multi-channel packet traversing downstream programs (data_ingestion.py) every secondsPerPakcet seconds.

        so we group packets with start times within secondsPerPacket/2 seconds of each other.
        """
        # retrieve first raw single-channel orb packet
        if not self.last_packet_stream:
            packet = self.nextpacket() 
            st = OrbserverClient.packet2stream(packet)
        else:
            st = self.last_packet_stream
            self.seek(self.last_packet_id)

        # keep grouping single-channel orb packets into a grouped Stream packet until we get one no longer within half a packet length of the first
        # note that packets that are than older first packet would still get grouped
        first_time = st[0].stats.starttime
        same_time = True
        old_packets= []
        while same_time and len(st)<3:
            packet = self.nextpacket()
            this_st = OrbserverClient.packet2stream(packet)
            this_time = this_st[0].stats.starttime
            if this_time > first_time + self.secondsPerPacket/2:
                same_time = False
            elif this_time < first_time - self.secondsPerPacket/2: # we've got an old packet
                ''' SCAFFOLD: hack to deal with old packets '''
                old_packets.append(this_st)
                if len(old_packets)==3:
                    self.last_packet_stream = st # stash the whole new grouped packet we were building
                    st = Stream(old_packets[0])
                    for st1 in old_packets[1:]:
                        st = st + st1
                return st                
            else:
                st.append(this_st[0])
        self.last_packet_stream = this_st
        if verbose:
            print('This packet is being saved for next time: \n', self.last_packet_stream)
        return st
    
# translates wildcards into antelope's atypical format
def replace_wildcard(input):
    input = input.replace('*', '.*')
    input = input.replace('?', '.')
    return input