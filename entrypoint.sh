#!/bin/bash

# Start Xvfb (Virtual Monitor) in the background
# This creates a fake 1920x1080 screen
Xvfb :99 -screen 0 1920x1080x24 &

# Wait 2 seconds for the screen to turn on
sleep 2

# Start your Bot
python main.py