#!/bin/bash
if pgrep python3  >/dev/null
then
  echo "Steam Control app is running."
else
  echo "Steam Control app is not running... Starting it now"
  /home/pi/SteamControl/SteamControl.py >> /tmp/SteamDebug.log  2>&1 &
fi

