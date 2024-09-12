#!/bin/bash
sudo systemctl stop threshold_monitor
sudo systemctl stop watch_threshold_monitor
pkill -f threshold_monitor.py
pkill -f watch_threshold_monitor.py

