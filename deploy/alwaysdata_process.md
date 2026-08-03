# Keep the bot running on alwaysdata

The bot has **no HTTP port** (Slack Socket Mode = outbound websocket), so it runs
as a **long-running "user program" site** that alwaysdata supervises and
restarts automatically.

## 1. Create the site (keep-alive process)

alwaysdata panel → **Web → Sites → Add a site**:

- **Addresses / name:** anything (e.g. `apk-telegram-bot`) — it won't serve HTTP.
- **Type:** `User program`
- **Command:**
  ```
  $HOME/codemagic-apk-telegram-bot/.venv/bin/python $HOME/codemagic-apk-telegram-bot/bot.py
  ```
- **Working directory:** `$HOME/codemagic-apk-telegram-bot`

Save. alwaysdata starts the process and relaunches it if it exits or the server
reboots.

## 2. Provide the tokens

Two equivalent options — pick one:

**Option A — `.env` file** (already supported by the bot):
```
ssh -i ~/.ssh/alwaysdata_KEY USER@ssh-USER.alwaysdata.net \
    nano $HOME/codemagic-apk-telegram-bot/.env
```

**Option B — alwaysdata Environment variables** (panel → **Environment**): add
`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
(and optionally `SLACK_CHANNEL_ID`, `CODEMAGIC_TOKEN`). The bot reads these from
the process environment, so they override / replace the `.env` file.

## 3. Restart & check

After setting tokens, restart the site (panel → Sites → restart) and check the
logs (panel → **Advanced → Logs**, or the site's log). You should see:
```
Starting Codemagic→Slack→Telegram APK bot (Socket Mode)…
```
Then trigger a Codemagic build to test end-to-end.
