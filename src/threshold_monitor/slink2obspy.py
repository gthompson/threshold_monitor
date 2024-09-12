#!/usr/bin/env python
"""
File: slink2obspy.py
Author: Glenn Thompson
Date: 2024-06-14
Description: This library provides a consistent data ingestion interface with orb2obspy and datascope2obspy for fetching the latest waveform data packet 
             from (in this case) a Seedlink server, as an ObsPy Stream object. Each packet contains waveform data for 1 SEED id (net.sta.loc.chan)

             SlinkClient (a new class, defined below) accomplishes this by subclassing and expanding ObsPy's EasySeedLinkClient class
"""
from obspy import Stream, UTCDateTime

from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from obspy.clients.seedlink.basic_client import Client as BasicSeedLinkClient
from obspy.clients.seedlink.slpacket import SLPacket

class SlinkClient(EasySeedLinkClient):

    DEFAULT_SERVER_URL = "137.229.32.109:18321"

    def __init__(self, server_url, starttime=None, secondsPerPacket=2.0):
        if server_url == 'default':
            server_url = self.DEFAULT_SERVER_URL 
        super().__init__(server_url, autoconnect=True)
        if starttime:
            self.move_pointer(starttime)
        self.last_packet_stream = None
        self.secondsPerPacket = secondsPerPacket

    def select_stream(self, network, station, location, channel):
        """ 
        Selects the Seedlink packet stream types that will be allowed from the SeedLink server

        Parameters:
            network (str): Select one or more network codes. Can be SEED network codes or data center defined codes. Multiple codes are comma-separated (e.g. "IU,TA"). Wildcards are allowed.
            station (str): Select one or more SEED station codes. Multiple codes are comma-separated (e.g. "ANMO,PFO"). Wildcards are allowed.
            location (str): Select one or more SEED location identifiers. Multiple identifiers are comma-separated (e.g. "00,01"). Wildcards are allowed.
            channel (str): Select one or more SEED channel codes. Multiple codes are comma-separated (e.g. "BHZ,HHZ").

        Returns:
            None 
        """    
        super().select_stream(network, station, selector=channel) # selector is like EHZ or EH?
        self.network = network
        self.station = station
        self.location = location
        self.channel = channel       

    def move_pointer(self, lastpacketendtime):
        """ does nothing. for consistency with orb2obspy """
        pass

    def nextpacket(self):
        """
        Reads next packet from seedlink server. Return packet object.
        """

        # initializing output data
        packet = None
        got_packet = False

        # Grabbing the next packet from the seedlink server
        while not got_packet:
            try:
                packet = self.conn.collect()
            except Exception as e:
                print('failed to read packet')
                print(e)
            else:
                if packet == SLPacket.SLTERMINATE:
                    self.on_terminate()
                    break
                elif packet == SLPacket.SLERROR:
                    self.on_seedlink_error()
                    continue

                # At this point the received data should be a SeedLink packet
                # XXX In SLClient there is a check for data == None, but I think
                #     there is no way that seedlinkclient.conn.collect() can ever return None
                assert isinstance(packet, SLPacket)

                packet_type = packet.get_type()

                # Ignore in-stream INFO packets (not supported)
                if packet_type not in (SLPacket.TYPE_SLINF, SLPacket.TYPE_SLINFT):
                    got_packet=True
    
        return packet

    def packet2stream(self, packet):
        """ converts a Seedlink packet into an ObsPy Stream containing 1 Trace """
        st = Stream()
        tr = packet.get_trace()
        tr.stats['loadtime']=UTCDateTime()
        if not self.secondsPerPacket:
            self.secondsPerPacket = tr.stats.endtime - tr.stats.starttime + tr.stats.delta
        st.append(tr)
        return st
   
    def nextpacket2Stream(self, starttime=None, verbose=False):
        """
        Fetches the next packet from a Seedlink server, and returns it as an ObsPy Stream

        Parameters:
            starttime (ObsPy UTCDateTime): ignored

        Returns:
            an ObsPy Stream object containing 1 Trace object, corresponding to the data packet
            
        """
        
        st = self.group_packets_by_time(verbose=verbose)
        return st
        
    def group_packets_by_time(self, verbose=False):
        """
        added this upon expansion from 1 to 33 channels. idea is to group packets from all 33 channels that share a common start time into a single Stream object, 
        so we only have one multi-channel packet traversing downstream programs (data_ingestion.py) every secondsPerPakcet seconds.

        so we group packets with start times within secondsPerPacket/2 seconds of each other.
        """    

        # retrieve first raw single-channel seedlink packet
        if not self.last_packet_stream:
            packet = self.nextpacket()
            st = self.packet2stream(packet)
        else:
            st = self.last_packet_stream

        # keep grouping single-channel seedlink packets into a grouped Stream packet until we get one no longer within half a packet length of the first
        # note that packets that are than older first packet would still get grouped
        first_time = st[0].stats.starttime
        same_time = True
        old_packets = []
        while same_time and len(st)<3:
            packet = self.nextpacket()
            this_st = self.packet2stream(packet)
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