#!/bin/bash
sudo cp threshold_monitor.service /etc/systemd/system/threshold_monitor.service
sudo cp watch_threshold_monitor.service /etc/systemd/system/watch_threshold_monitor.service
sudo systemctl daemon-reload
sudo systemctl restart threshold_monitor
sudo systemctl restart watch_threshold_monitor
