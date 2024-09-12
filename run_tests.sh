#!/bin/bash
source ${HOME}/.bashrc
conda activate obspy
RUN_DIR=${HOME}/run_threshold_monitor
cd $RUN_DIR
testsdir=${RUN_DIR}/tests
pytest -v $testsdir/test_threshold_monitor.py
#python $testsdir/test_threshold_monitor.py
