#!/bin/bash
source ${HOME}/.bashrc
conda activate obspy
RUN_DIR=${HOME}/run_threshold_monitor
SRC_DIR=${RUN_DIR}/src/threshold_monitor
if [ "$#" -ne 1 ]; then
	OUTPUTDIR="${RUN_DIR}/output"
else
	OUTPUTDIR="${RUN_DIR}/$1"
fi
pkill -f watch_threshold_monitor.py
cd $SRC_DIR
python watch_threshold_monitor.py -v -p threshold_monitor.yml -r 1 -o ${OUTPUTDIR}  
