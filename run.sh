#!/bin/bash
if pgrep -x "threshold_monitor.py"; then
	echo "threshold_monitor.py already running. stop it first"
	exit
fi
source ${HOME}/.bashrc
conda activate obspy
RUN_DIR=${HOME}/run_threshold_monitor
SRC_DIR=${RUN_DIR}/src/threshold_monitor
API="orb2obspy"
NSLC='AK.*..HN?'
LOGFILE=False
if [ "$#" -ne 1 ]; then
	OUTPUTDIR="${RUN_DIR}/output"
        LOGFILE="${OUTPUTDIR}/threshold_monitor.log"
	if [ -e $LOGFILE ]; then
		rm $LOGFILE
	fi
else
	OUTPUTDIR="${RUN_DIR}/$1"
fi
mkdir -p ${OUTPUTDIR}
rm -f ${OUTPUTDIR}/*.csv
cd $SRC_DIR
if [ ${LOGFILE} ]; then
    python threshold_monitor.py -l -p threshold_monitor.yml -a ${API} -n ${NSLC} -o ${OUTPUTDIR} #  > ${LOGFILE} &
else
    python threshold_monitor.py -l -p threshold_monitor.yml -a ${API} -n ${NSLC} -o ${OUTPUTDIR}
fi
