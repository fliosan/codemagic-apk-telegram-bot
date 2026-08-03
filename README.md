# Codemagic → Slack → Telegram APK bot

When **Codemagic** finishes a build and posts the APK download link to **Slack**,
this bot grabs the link, downloads the `.apk`, and sends the file to your
**Telegram** chat.

```
Codemagic build done
   └─ posts message + APK link  ──▶  Slack channel
                                       └─ this bot (Socket Mode) sees the link
                                            ├─ downloads the .apk
                                            └─ sends it  ──▶  your Telegram
```

No public server or webhook URL is needed — Slack **Socket Mode** uses an
outbound websocket, so this runs fine on your laptop, a Raspberry Pi, or any
small VPS.

**Handles big APKs.** Telegram's Bot API stops at 50 MB, which most release
builds exceed. Add two extra values (step 3 below) and the bot uploads via
MTProto instead — real, forwardable files up to ~800 MB, no expiring links.

---

## Configuration at a glance

Everything lives in `.env` (copy it from [`.env.example`](.env.example)):

| Variable | Required | What it is |
|---|---|---|
| `SLACK_BOT_TOKEN` | ✅ | `xoxb-…` — Bot User OAuth Token |
| `SLACK_APP_TOKEN` | ✅ | `xapp-…` — App-Level Token, `connections:write` scope |
| `TELEGRAM_BOT_TOKEN` | ✅ | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | ✅ | Where APKs are sent (`python get_chat_id.py`) |
| `SLACK_CHANNEL_ID` | recommended | Restrict the bot to one channel (`C…`) |
| `TG_API_ID` + `TG_API_HASH` | for files >50 MB | From [my.telegram.org](https://my.telegram.org) |
| `CODEMAGIC_TOKEN` | rarely | Only if artifact links return 401/403 |

---

## Setup

### 1. Install
```bash
cd codemagic-apk-telegram-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Create the Telegram bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token into
   `.env` as `TELEGRAM_BOT_TOKEN`.
2. Open your new bot in Telegram and press **Start** (send it any message).
3. Find your chat id:
   ```bash
   python get_chat_id.py
   ```
   Put the printed number into `.env` as `TELEGRAM_CHAT_ID`.

### 3. Enable big-file upload (optional — do it if your APKs exceed 50 MB)
1. Open <https://my.telegram.org> → log in with your phone number.
2. **API development tools** → create an app (any title, platform *Other*).
3. Copy **App api_id** → `.env` as `TG_API_ID`, and **App api_hash** →
   `TG_API_HASH`.

These identify the *app*, not your account; combined with the bot token above,
the bot uploads as itself. Skip this and files over 50 MB arrive as a download
link instead of a file.

### 4. Create the Slack app (Socket Mode)
1. Go to <https://api.slack.com/apps> → **Create New App** → *From scratch*.
2. **Socket Mode** → enable it → generate an **App-Level Token** with the
   `connections:write` scope → copy into `.env` as `SLACK_APP_TOKEN` (`xapp-…`).
3. **OAuth & Permissions** → add Bot Token Scopes:
   `channels:history`, `groups:history`, `chat:write`. Install the app to the
   workspace → copy the **Bot User OAuth Token** into `.env` as
   `SLACK_BOT_TOKEN` (`xoxb-…`).
4. **Event Subscriptions** → enable → subscribe to bot events:
   `message.channels` (and `message.groups` for private channels).
5. In Slack, **invite the bot** to the channel where Codemagic posts:
   `/invite @your-bot`.
6. *(Optional)* To restrict the bot to that one channel, copy the channel id
   (right-click channel → *View channel details* → bottom) into
   `SLACK_CHANNEL_ID`.

### 5. Point Codemagic at Slack
In Codemagic → your app → **Publish** → **Slack**: connect your workspace, pick
the channel, and enable **"Post build artifact links"** (so the message contains
the `.apk` download URL).

The bot recognises both link shapes: Codemagic's signed artifact links, whose
*label* is the filename (`<https://api.codemagic.io/artifacts/…|app-release.apk>`),
and plain URLs ending in `.apk`. When a build publishes several APKs it prefers
the `universal` one and uses the real artifact name as the Telegram filename.

### 6. Run
```bash
python bot.py
```
Trigger a Codemagic build — when it posts to Slack, the APK lands in your
Telegram. 🎉

---

## Deploy to a VPS (always-on)

Because the bot uses Socket Mode (outbound websocket), **any always-on Linux box
works** — no public IP, domain, or open ports needed. Pick a cheap VPS
(Hetzner, DigitalOcean, Oracle free tier).

```bash
# 1. Copy the bot folder to the VPS
scp -r codemagic-apk-telegram-bot/ root@YOUR_VPS:/root/

# 2. SSH in and run the installer
ssh root@YOUR_VPS
cd /root/codemagic-apk-telegram-bot
sudo bash deploy/setup.sh         # installs python, venv, user, systemd service

# 3. Fill in your tokens, then restart
sudo nano /opt/apkbot/.env
sudo systemctl restart apkbot
```

The installer ([`deploy/setup.sh`](deploy/setup.sh)):
- installs `python3` + venv,
- copies the app to `/opt/apkbot`,
- creates a dedicated unprivileged `apkbot` user,
- installs deps into a virtualenv,
- installs & enables the hardened systemd unit
  ([`deploy/apkbot.service`](deploy/apkbot.service)) so it auto-starts on boot
  and auto-restarts on crash.

Manage it:
```bash
systemctl status apkbot
journalctl -u apkbot -f          # live logs
```

To update later: re-copy the folder and re-run `sudo bash deploy/setup.sh`.

---

## Notes & limits

- **File-size behaviour:** APKs up to 50 MB go via the Bot API (instant).
  Larger ones use MTProto when `TG_API_ID`/`TG_API_HASH` are set — real files
  up to ~800 MB, a few minutes for a ~120 MB build. Above that (or with the
  MTProto vars unset) the bot sends the Codemagic download link instead.
- **Missed a delivery?** `python replay_last_build.py` re-runs the newest
  artifact message in the channel through the pipeline — handy after downtime
  or when testing parser changes, without re-posting anything to Slack.
- **Private artifact links:** Codemagic's Slack links are usually public. If a
  download returns 401/403, set `CODEMAGIC_TOKEN` in `.env` and the bot retries
  with the `x-auth-token` header.
- **Keep it running:** for an always-on setup, run under `systemd`,
  `pm2`, `tmux`, or a tiny VPS. Example systemd unit:
  ```ini
  [Unit]
  Description=Codemagic APK Telegram bot
  After=network-online.target

  [Service]
  WorkingDirectory=/path/to/codemagic-apk-telegram-bot
  ExecStart=/path/to/.venv/bin/python bot.py
  Restart=always
  EnvironmentFile=/path/to/codemagic-apk-telegram-bot/.env

  [Install]
  WantedBy=multi-user.target
  ```
- `.env` and `*.apk` are git-ignored — never commit your tokens.
