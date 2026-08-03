#!/usr/bin/env python3
"""Helper: prints your Telegram chat id.

1. Open Telegram, find your bot, press Start / send it any message.
2. Run:  python get_chat_id.py
3. Copy the chat id into .env as TELEGRAM_CHAT_ID.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.environ["TELEGRAM_BOT_TOKEN"]
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
data = r.json()
if not data.get("ok"):
    print("Telegram error:", data)
    raise SystemExit(1)

results = data.get("result", [])
if not results:
    print("No messages yet. Send your bot a message first, then re-run.")
    raise SystemExit(0)

seen = {}
for upd in results:
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat = msg.get("chat")
    if chat:
        seen[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name", "")

for cid, who in seen.items():
    print(f"chat_id = {cid}    ({who})")
