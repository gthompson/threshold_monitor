# In a nutshell
**threshold_monitor** is an application (consisting of several Python and bash scripts) designed to compute Peak Ground Acceleration (PGA) from strong-motion accelerometer data the Trans-Alaska Pipeline System Earthquake Monitoring System (TAPS-EMS) stations, compare these to pre-defined thresholds, and send threshold alarms. Packet latency is also monitored, and latency alarms are also sent. 

# Motivation
The **threshold_monitor** package is intended as an Antelope-independent replacement for [orbtm.c](https://github.com/akquake/antelope/blob/master/bin/rt/orbtm/orbtm/orbtm.c), a C program which has been used by AEC and Alyeska Pipeline Company for threshold monitoring of TAPS-EMS since 2008. By being written in the popular Python programming language and leveraging the [ObsPy toolbox](https://github.com/obspy/obspy), **threshold_monitor** will be easier to maintain and further develop.

# Code
The code tree currently looks like:

![image](https://github.com/user-attachments/assets/b684b0c3-7a00-48ed-a396-5d89e9991e6d)

The individual scripts and configuration files will be discussed later, once we've covered how to install, test, run, and deploy the application. Such information is also covered in detail in the relevant man pages.

# Installation
## Cloning the git repository
The **threshold monitor** package is located in the akquake/antelope github repository under the orbtm_simulation branch at [[https://github.com/akquake/antelope/tree/orbtm_simulation/bin/rt/threshold_monitor]]

```
cd
git clone https://github.com/akquake/antelope antelope
git checkout orbtm_simulation
```

## Setting up conda
Instructions to install miniconda are at [[https://docs.anaconda.com/miniconda/#quick-command-line-install]]
Currently, the instructions for Linux are:

```
mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
~/miniconda3/bin/conda init bash
~/miniconda3/bin/conda init zsh
```

## Setting up a conda environment

The **threshold_monitor** package needs several packages to be installed. It is best to install these within a (mini)conda environment. Instructions are:

The code runs under a conda environment called "obspy" (sorry, this is hardwired for now, it must be called "obspy"), created from the environment.yml file:

```
cd ~/antelope/bin/rt/threshold_monitor
conda env create -f environment.yml
conda activate obspy
```

If this does not work, try:

```
conda config --add channels conda-forge
conda create -n obspy python=3.10 obspy cartopy pytest pytest-json pytest-json-report geographiclib
conda activate obspy
conda install pandas 
conda install anaconda::pyyaml
# conda install filelock (commenting here, as removed this dependency today, but not fully tested yet)
conda install mysql-connector-python
```

If mysql-connector-python fails to install, do it via pip instead:
`pip install mysql-connector-python`

_watch_threshold_monitor.py_ checks to see if mysql (the Python package) is installed. If it is, it will try to generate the occ_display mysql table. Otherwise, it only generates a pandas DataFrame. But extra steps are also needed to install MySQL and phpMyAdmin: Luke and Nick did that.

## Installing the code
The _install.sh_ script will install the application from the local git repository to a directory called _~/run_threshold_monitor_ 
Warning: this will erase that directory if it already exists, and write it again, to create a clean run environment.

```
./install.sh
```

This also installs man pages to _~/run_threshold_monitor/man/man1/_, which should allow them to be discoverable due to the following line in ~/.bashrc:

``` 
export MANPATH="$(manpath -g):$HOME/run_threshold_monitor/man"
```

# Testing 

Before running the application (next step), it is recommended to run through a sequence of tests (a test plan). This is done with:

```
cd ~/run_threshold_monitor
./run_tests.sh
```

[_test_threshold_monitor.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/test/test_threshold_monitor.py) uses pytest to incrementally test everything required for _threshold_monitor.py_ to work properly. It can be run by the Bash shell script [_run_tests.sh_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/test/run_tests.sh). pytest automatically detects any functions in _test_threshold_monitor.py_ that begin with "test_" and runs them. Below is an example of running on the MacMini "strain" on 202408/22: 

![image](https://github.com/user-attachments/assets/81355b60-bc23-495d-a0c7-a3b70fbcb0ef)

The list of tests currently implemented are:
* test_command(): tests that run_command() works - needed for subsequent tests
* test_inventory(): tests that the [StationXML file](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/pipeline_stations.xml) can be loaded by ObsPy's read_inventory method. Crucial for calibrating waveform data, or removing the full instrument response.
* test_calib2obspy_1channel(): tests that calibration data from the AEC Datascope master_stations database can be loaded and applied. This is no longer implemented within _threshold_monitor.py_, as the primary metadata source is a StationXML file. This uses [_calib2obspy.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/dataclients/calib2obspy.py), which is modelled on theinstrument response removal process in ObsPy.
* test_iris_vs_aec_calibrations(): This checks that calibration data from the StationXML file and master_stations agree with each other, by comparing the amplitude of waveform data corrected using each metadata source, for each of the 33 TAPS-EMS strong motion accelerometer channels.
* test_data_ingestion_1channel_orb2obspy(): this runs _data_ingestion.py_ for 1 channel using the _orb2obspy.py_ API. We test _data_ingestion.py_ before _threshold_monitor.py_ which builds on it. We test 1 channel first, then 1 station (3 channels), then all channels (11 stations x 3 channels = 33 channels), and we also test each API, as you will see in the following tests, which should be self-explanatory ...
* test_data_ingestion_1station_orb2obspy():
* test_data_ingestion_1channel_slink2obspy():
* test_data_ingestion_1station_slink2obspy():
* test_data_ingestion_1channel_datascope2obspy():
* test_data_ingestion_1station_datascope2obspy():

Then the tests for _threshold_monitor.py_:
* test_threshold_monitor_1channel_orb2obspy():
* test_threshold_monitor_1station_orb2obspy():
* test_threshold_monitor_allchannels_orb2obspy():
* test_threshold_monitor_allchannels_slink2obspy():
* test_threshold_monitor_allchannels_datascope2obspy():

It then re-runs _threshold_monitor.py_ for select data archived in Datascope databases (using the _datascope2obspy.py_ API):
* test_alarms(): this is actually a meta-test, with one test for each of a series of alarms previously issued by _orbtm.c_, identified by Natalia in the spreadsheet [_TM_alarms.csv_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/test/TM_alarms.csv). It simply checks that _threshold_monitor.py_ successfully completes for a timewindow of data around each alarm.
* test_do_alarm_times_match(): This checks that the alarm times  issued by test_alarms() match those in _TM_alarms.csv_. (This test now fails because we have added new features into _threshold_monitor.py_ that were not implemented in _orbtm.c_, such as a threshold alarm timeout, resulting in different behaviour).
* test_do_alarm_status_match(): This checks that the alarm statuses ("low", "medium", or "high") issued by test_alarms() match those in _TM_alarms.csv_. (This test now fails because we have added new features into _threshold_monitor.py_ that were not implemented in _orbtm.c_, such as a threshold alarm timeout, resulting in different behaviour).
* test_CIGO_power_cycle(): this is a stub for running _threshold_monitor.py_ on a sequence of data from a test deployment of a Q8 at CIGO, which was power-cycled on 2024/08/14. It is a first step to seeing how _threshold_monitor.py_ behaves in response to power transients. However, _wf2obspy.py_ (which is used by _datascope2obspy.py_) fails to load data from 'HT.10627..HNZ' because it is hardwired to use the AEC master_stations database, which does not include temporary installations.

To run just a subset of tests, comment out some of the test_* function definitions. By default, the tests run on a 60-s time window of data (the DURATION setting in _test_threshold_monitor.py_, and since they are using real-time data, this means each test takes about 60-s to run. The test_alarms() function uses a time window that is 4 times longer, by default, but these run quickly because the data is already archived in the default AEC Datascope waveforms database (_wf2obspy.py_ knows how to find this database).

# Running the application

To be able to run the application, first change to the run directory. Then to run a default configuration of the threshold_monitor.py program, use _run.sh_:

```
cd ~/run_threshold_monitor
./run.sh
```

By default, this will create the directory _~/run_threshold_monitor/output_ (emptying if it already exists). Or optionally, a different subdirectory can be passed as a command line argument to _run.sh_

It then runs _threshold_monitor.py_ by issuing the command:
``` python threshold_monitor.py -v -l -p threshold_monitor.yml -a orb2obspy -n 'AK.*..HN?' -o output > output/threshold_monitor.log & ```

Output is logged to _~/run_threshold_monitor/output/threshold_monitor.log_. This is the first place to look to debug code. If the code runs, several CSV files will also be created in the same directory. 

See the threshold_monitor man page for more details.

``` man threshold_monitor ```

if this does not work, it indicates that either _install.sh_ was not able to install man pages to the proper directory, or the $MANPATH variable was not appended to in _~/.bashrc_. In this case, view man pages with:

``` man ~/run_threshold_monitor/src/threshold_monitor/threshold_monitor.1 ```

**NOTE: WE PROBABLY NEED TO ADD SOMETHING TO TRIM THIS LOG FILE AND THE CORRESPONDING CSV FILES** 

# Running the watch program

The purpose of _watch_threshold_monitor.py_ is to check that _threshold_monitor.py_ is running, and to provide a stronger check on data latency, as well as to provide a state matrix (as a MySQL table) that always gives a current snapshot of data latency and threshold status for each station (similar to the OCC_display pipeline matrix in the previous generation of the TAPS-EMS software). An Asana task has also been added in Sprint 11 to migrate all alarming functionality from _threshold_monitor.py_ and _data_ingestion.py_ to _watch_threshold_monitor.py_, which Nick is handling.

The CSV files spat out by _threshold_monitor.py_ are monitored by _watch_threshold_monitor.py_, which tracks latency and threshold status for each station, and if MySQL is installed, refreshes the occ_display table. The easy way to run this is:

```
cd ~/run_threshold_monitor
./run_watch.sh
```

The command actually run is:
``` 
cd ~/run_threshold_monitor/src/threshold_monitor
python watch_threshold_monitor.py -v -l -p threshold_monitor.yml -r 1 -o output 
```

This keeps updating a pandas DataFrame, refreshing the Terminal output, and the MySQL table OCC_DISPLAY:
![image](https://github.com/user-attachments/assets/e4077011-77f7-4497-a8fb-1be7d7a37230)

# Deployment as a daemon service

To deploy the application to run under systemctl:

```
cd ~/antelope/bin/rt/threshold_monitor
./deploy.sh
```

This should only be run after _run_tests.sh_, _run.sh_, and _run_watch.sh_ (previous steps) have been verified to work.

_deploy.sh_ will try to kill any existing threshold_monitor jobs. This is to prevent any confusion/bugs. Output files will go into _~/run_threshold_monitor/daemonfiles/_ (rather than to _~/run_threshold_monitor/output_).

It also: 
* copies the _threshold_monitor.service_ script to /etc/systemd/system
* copies the _watch_threshold_monitor.service_ script to /etc/systemd/system
* under systemctl it reloads the daemon, and 
* restarts the threshold_monitor service, which invokes the contents of _threshold_monitor.service_. This in turn 
* calls _run.sh_, which starts _threshold_monitor.py_, and
* restarts the watch_threshold_monitor service, which invokes the contents of _watch_threshold_monitor.service_. This in turn 
* calls _run_watch.sh_, which starts _watch_threshold_monitor.py_

# Stopping everything running

The easy way to stop every instance of _threshold_monitor.py_ and _watch_threshold_monitor.py_ that is running, including daemon processes, is to use _stop.sh_:

`./stop.sh`

# Python Scripts

The main program is [_threshold_monitor.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/threshold_monitor.py). The following diagram shows the relationship between the various Python codes that are imported by _threshold_monitor.py_, including the classes that are inherited:

<img width="1077" alt="image" src="https://github.com/user-attachments/assets/c4a564bf-2b37-4eab-9c48-03d7d49b0e8f">

_threshold_monitor.py_ leverages [_data_ingestion.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/data_ingestion.py), by inheriting and subclassing the RealTimeDataClient class (as MyDataClient), and overriding the analyze() method. 

_data_ingestion.py_ retrieves multi-channel waveform data packets (as ObsPy Stream objects), merges them with a waveform data buffer (also an ObsPy Stream object), then processes a temporary copy of the waveform data buffer (detrend, pad, taper, filter, unpad to remove tapered section), trims the processed waveform data packet out of the data buffer, and presents this to the analyze() method for further processing. The analyze() method in _data_ingestion.py_ does nothing, thus _data_ingestion.py_ can be thought of as a generic framework that does the heavy lifting of retrieving and processing packetized waveform data from various data sources (orbservers, Seedlink servers, databases) via dedicated [APIs](#apis), for other applications to build on.

_threshold_monitor.py_ is one such application. It redefines the analyze() method to: (i) compute PGA values, (ii) compare them to pre-defined station PGA thresholds from a YML-format parameter file, (iii) declare threshold exceedance detections, and then (iv) processes these detections into threshold alarms.

_threshold_monitor.py_ is also multi-threaded. One thread is run per station. A multi-channel packet will typically contain waveform data for 3 channels (vertical, north-south, and east-west) of a strong motion accelerometer. For example, for station PS01 the corresponding SEED ids are "AK.PS01..HNZ", "AK.PS01..HNN", and "AK.PS01..HNE", which can be selected with "AK.PS01..HN?" (we do not process data from the co-located broadband seismometer for PGA calculation). Since _data_ingestion.py_ also monitors packet latency and issues latency alarms, _threshold_monitor.py_ also inherits this ability (enabled through the -l command line option). 

# APIs
_data_ingestion.py_ has the ability to retrieve packets from Antelope orbservers and Seedlink servers and simulated packets from Datascope CSS3.0 databases via data client APIs. The corresponding programs are [_orb2obspy.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/orb2obspy.py), [_slink2obspy.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/slink2obspy.py), and [_datascope2obspy.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/datascope2obspy.py) that implement the same interface to _data_ingestion.py_. These codes contain the respective classes OrbserverClient, SlinkClient, and DatascopeClient, that each implement methods called select_stream(), which uses an expression to subset packets to those matching the requested SEED ids (network-station-location-channel combinations), and nextpacket2Stream(), which retrieves the next packet and converts it to an ObsPy Stream object. Each orbserver packet contains 1-s of waveform data for one SEED id. Seedlink server packets have a variable length, but still only contain waveform data for one SEED id. However, it is more efficient to process a multi-channel packet, containing data from all 3 accelerometer channels, rather than process three single-channel packets separately, so the group_packets_by_time() method is designed to bundle 3 single-channel packets into a single 3-channel packet. This also makes the buffer-based processing logic in _data_ingestion.py_ simpler.

Note that _datascope2obspy.py_ leverages the get_waveforms() function from [_wf2obspy.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/pymodules/wf2obspy.py), which is copied into the right place by the _install.sh_ script.

# Output files
A latency CSV file and threshold history CSV file are generated for each station by _threshold_monitor.py_ (due to one thread per station). For example, these will be called latency_PS01.csv and threshold_PS01.csv for station PS01.

Here, for example, are the first few rows of the latency_PS01.csv file:
![image](https://github.com/user-attachments/assets/805a6b8d-6a88-48dc-824e-9b44eaf71aba)

Here, the columns are the id, starttime and endtime of the ObsPy Trace object in the corresponding 3-channel packet ObsPy Stream object, the latency (in seconds), and the packet duration (in seconds). The latency is the difference between when the packet was loaded (presumably within a fraction of a second of the packet being written to the orbserver), and the newest data available in the packet. 

And the first few rows of the threshold_history_PS01.csv file:
![image](https://github.com/user-attachments/assets/0ce6c2a3-089a-412d-8ad9-ad76bbd3e846)

Here, the columns are the starttime and endtime of the Trace object in the corresponding 3-channel packet Stream object, the time at which the peak value within this time window is recorded, the peak value (in m/s^2), and the corresponding threshold status ("OFF", "LOW", "MEDIUM", or "HIGH"). In this example, you can see that for packets acquired from an orbserver, the packet length is always 1-s, and the waveform data for each channel are perfectly aligned. 

If _threshold_monitor.py_ is run for a limited duration (rather than forever), it will also generate a plot of the data in each CSV file. Here, for example, is a screenshot of the files output by the test_threshold_monitor_allchannel_orb2obspy() function in _test_threshold_monitor.py_ [see Testing section below](#testing).

![image](https://github.com/user-attachments/assets/2aaae33e-07c2-4d52-8e31-a52d4e5caa9e)

And here is one of the latency PNG files produced at the end of the run:

![image](https://github.com/user-attachments/assets/c8ae8a3f-da11-4da2-9e3c-8bb4fd8de599)

A similar figure is generated, and deposited in the same folder, whenever a latency alarm is issued.

And one of the threshold PNG files:

![image](https://github.com/user-attachments/assets/ef892ee5-2fdb-4a09-9ae9-20cff61f7696)

A similar figure is generated, and deposited in the same folder, whenever a threshold alarm is issued.

The CSV files are also monitored by [_watch_threshold_monitor.py_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/watch_threshold_monitor.py), which will spot if these files stop being updated - suggesting either a data outage, or that _threshold_monitor.py_ has stopped running. 



# Parameter file

The default parameter file is [_threshold_monitor.yml_](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/threshold_monitor.yml), which currently looks like:

```
api: orb2obspy
#datasource: 137.229.32.211:6520
datasource: default
mode: realtime
filterdef: 
  type: highpass
  freq: 
    - 0.05
  corners: 4
  zerophase: False
duration: -1 # run forever if -1
bufferSecs: 10.0
secondsPerPacket: 1.0
nslc: AK.*..HN? # stations will only be used if they are defined in the thresholds dict AND they match this regular expression
#nslc: HT.10627..HNZ
xmlfile: pipeline_stations.xml
maximum_latency: 600.0 # packets with latency exceeding this will trigger a latency alarm, and not get processed into PGA values
threshold_alarm_timeout: 60.0 # block new alarms at same station for this many seconds after a threshold alarm, unless the status increases (e.g. from LOW to MEDIUM) within this time period
latency_alarm_timeout: 60.0 # block new alarms at same station for this many seconds after a latency alarm
email_list: 
- gthompson@alaska.edu
remove_instrument_response: False
thresholds: # station will only be used if defined here AND matches nslc filter regular expression
  PS01: 
    LOW: 0.05
    MEDIUM: 0.10
    HIGH: 0.15
  PS04: 
    LOW: 0.05
    MEDIUM: 0.10
    HIGH: 0.15
  PS11: 
    LOW: 0.05
    MEDIUM: 0.10
    HIGH: 0.15
  PS05: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.20
  PS06: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.20 
  PS07: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.20
  PS08: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.20
  PS09: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.20
  PS10: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.25
  PS12: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.25
  VMT: 
    LOW: 0.08
    MEDIUM: 0.15
    HIGH: 0.25

(mysql logon omitted)

```

This is described further in the [corresponding man page](https://github.com/akquake/antelope/blob/orbtm_simulation/bin/rt/threshold_monitor/src/threshold_monitor/threshold_monitor.1) for _threshold_monitor.py_ 

# Miscellaneous comments
## Out-of-order packets
Underlying APIs present each new packet as an ObsPy Stream object which should contain 3 Trace objects for the HNZ/N/E channels of one TAPS station strong motion sensor. It is assumed that time-overlapping packets (within half a packet length) for all 3 channels arrive sequentially, in which case they are grouped into a single 3-channel packet ObsPy Stream object. orbserver packets are 1-s long, and aligned within a subsample of each other. The code has been modified to handle packets that arrive out-of-time order, but this has not been tested, because there is not an obvious way to simulate this! Therefore, if and when this happens in reality, results are not guaranteed and _threshold_monitor.py_ could crash. 

## Buffering
There is an attempt to merge each packet Stream with a longer waveform data buffer (also an ObsPy Stream object), prior to detrending, filtering, and calibration. This stabilizes the detrending, filtering, and if requested, full instrument response removal. However, should this fail, or should buffering be disabled because no filterdef or non-zero bufferSecs is set in the YML paramater file, then the packet Stream will be processed as a 'detached packet'. In this case, the mean (DC) offset is removed, and a calibration value applied.

## Benchmarking
This is enabled by the -b command line option, but currently the benchmarking summary is only produced at the end of the program. It would probably be a good idea to update and output this periodically, e.g. hourly. Here is an example of the benchmarking output for one of the tests:

```
SUMMARY:
# time windows = 62
Label initial_setup took  0.56 seconds: average   9.1 milliseconds per time window
Label nextpacket2Stream took  3.98 seconds: average  64.2 milliseconds per time window
Label load_loop_update took  0.00 seconds: average   0.0 milliseconds per time window
Label buffer_setup took  0.00 seconds: average   0.0 milliseconds per time window
Label calibrate took  0.17 seconds: average   2.8 milliseconds per time window
Label return_process took  0.01 seconds: average   0.2 milliseconds per time window
Label computing_max took  0.01 seconds: average   0.1 milliseconds per time window
Label threshold_exceedance took  0.03 seconds: average   0.5 milliseconds per time window
Label return_analyze took  0.61 seconds: average   9.8 milliseconds per time window
Label buffer_update took  0.20 seconds: average   3.2 milliseconds per time window
Label buffer_filtering took  0.36 seconds: average   5.8 milliseconds per time window
Label buffer_trim2packet took  0.16 seconds: average   2.5 milliseconds per time window
```

# Links
* [initial requirements analysis, 2024/05/15](https://docs.google.com/document/d/1PppsaCcnEjdI9CJXHZGil5j6ZLhkRusE6TpqwplFA3E/edit?usp=sharing)
* [osmium system diagram](https://drive.google.com/file/d/1-6X0YUwxU2_r54TTkDjozV5Cp1Vug_8x/view?usp=sharing) and [Gabe's notes](https://docs.google.com/document/d/1zdTt_2Vji_pl3SrhtjjNCQXuf-ka_33GHsAVXKDs-Ic/edit?usp=sharing)
* [Review of orbtm.c on 2024/06/02](https://docs.google.com/document/d/1PZFVNyG0wacLHbbmeSI9TSJXsBvWndhUKvNni17OMgs/edit?usp=sharing)
* [Initial benchmarking and latency results, 2024/06/04](https://docs.google.com/document/d/1AGxM1oyB7hLesFG4sK5akddyFoXbZxm5fyweBA9c8Uk/edit?usp=sharing)
* [Natalia's original spreadsheet of threshold alarms sent by orbtm.c](https://docs.google.com/spreadsheets/d/15OEb2GmBnyWbLa5J_gJW3GwwplEzXvZFFdonqg14nkQ/edit?usp=sharing)
* [Overview presentation given on 2024/06/24](https://docs.google.com/presentation/d/1Im3OQdZTxybix_owuguAAEJRF70g-zKW0c0cJkO_Vto/edit?usp=sharing)

***

Author: Glenn Thompson, 2024/08/15
Last modified: Glenn Thompson, 2024/08/23
