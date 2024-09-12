#!/bin/bash
RUN_DIR="${HOME}/run_threshold_monitor"
# Stop any services already running
sudo systemctl stop threshold_monitor
sudo systemctl stop watch_threshold_monitor
# Kill any lingering jobs
pkill -f watch_threshold_monitor.py
pkill -f threshold_monitor.py
# clean up the run directory
if [ -e $RUN_DIR ]; then
	rm -rf $RUN_DIR/*
else
	mkdir -p $RUN_DIR
fi
cp -r * $RUN_DIR
# copy wf2obspy
#cp ../../pymodules/wf2obspy.py $RUN_DIR/src/threshold_monitor/
# install man pages
mkdir -p $RUN_DIR/man/man1
mv $RUN_DIR/src/threshold_monitor/*.1 $RUN_DIR/man/man1
