#!/usr/bin/env python3
"""Replay the newest Slack message containing an APK artifact through the
bot's own parser + delivery pipeline. Used to recover a missed delivery or to
test parser changes against real Codemagic payloads without posting to Slack."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import requests
import bot  # noqa: E402  (needs env loaded first)

CHANNEL = os.environ.get("SLACK_CHANNEL_ID")
if not CHANNEL:
    sys.exit("Set SLACK_CHANNEL_ID in .env to the channel Codemagic posts to.")
TOK = os.environ["SLACK_BOT_TOKEN"]

r = requests.get(
    "https://slack.com/api/conversations.history",
    params={"channel": CHANNEL, "limit": 10},
    headers={"Authorization": f"Bearer {TOK}"},
    timeout=30,
).json()
if not r.get("ok"):
    sys.exit(f"Slack API error: {r.get('error')}")

for msg in r["messages"]:
    link = bot.find_apk_link(msg)
    if link:
        url, name = link
        label = bot.extract_build_label(msg)
        print(f"Parsed APK link: name={name!r} build={label!r} url={url[:90]}…")
        bot.handle_apk(url, name, label)
        print("Replay done — check Telegram.")
        break
else:
    print("No APK link found in the last 10 messages.")
