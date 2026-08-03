#!/bin/bash
# Entry point for a supervised service (e.g. the alwaysdata panel:
# Advanced -> Services). Takes the same lock as run_forever.sh so the two
# mechanisms can never start a second bot instance; the lock fd survives
# exec into python.
cd "$(dirname "$0")" || exit 1
exec 9>.bot.lock
flock -n 9 || exit 1
exec ./.venv/bin/python bot.py >> bot.log 2>&1
