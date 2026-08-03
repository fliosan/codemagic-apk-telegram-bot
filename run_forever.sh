#!/bin/bash
# Keep the APK bot alive: single instance via flock, restart on crash.
cd "$(dirname "$0")" || exit 1
exec 9>.bot.lock
flock -n 9 || exit 0   # already running
while true; do
  ./.venv/bin/python bot.py >> bot.log 2>&1
  echo "$(date) bot exited ($?), restarting in 10s" >> bot.log
  sleep 10
done
