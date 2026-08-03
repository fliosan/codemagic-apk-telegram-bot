#!/bin/bash
# Cron / scheduled-task entry point (e.g. a crontab, or the alwaysdata panel).
# run_forever.sh holds a flock: if the bot is alive this exits instantly;
# if the server rebooted, this brings the bot back. setsid detaches it
# from the cron process group so task cleanup cannot kill the bot.
DIR="$(cd "$(dirname "$0")" && pwd)"
setsid nohup "$DIR/run_forever.sh" >/dev/null 2>&1 &
exit 0
