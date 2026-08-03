# APK Delivery Bot — V2 ideas

Deferred features. V1 is live: Slack channel → server bot → Telegram. This doc is the implementation plan for when V2 is wanted.

## 1. Build lifecycle notifications (started / finished / failed / cancelled)

**No webhook needed** — Codemagic already posts these as Slack messages to the build channel
("Build #8 for app MyApp started by …", "Build #8 1.0.1 … finished", "Build #1 … failed").
The bot receives all of them and currently ignores non-APK messages.

Implementation (~10 lines in `bot.py`, inside `on_message`):
- Regex the message text/attachments for `Build #(\d+).*(started|finished|failed|cancelled)`.
- Map to emoji (▶️ ✅ ❌ 🚫) and `telegram_send_message(...)`.
- Keep the existing APK flow untouched — a "finished" message with an `.apk` link
  produces both the status line and the file/link.
- Optional `.env` flag `NOTIFY_BUILD_STATUS=1` to toggle.

A true Codemagic **webhook receiver** was considered and rejected: needs an inbound
HTTP endpoint (alwaysdata "site" + WSGI app), adds infra for no extra information
over the Slack route.

## 2. Control Codemagic from Telegram (start / cancel / status)

Bot currently only *sends* to Telegram. Add a second thread/task polling
`getUpdates` (long-poll) and handle commands **only from TELEGRAM_CHAT_ID** (auth!):

- `/build dev` / `/build prod` → `POST https://api.codemagic.io/builds`
  body: `{"appId": ..., "workflowId": ..., "branch": "main"}`,
  header `x-auth-token: CODEMAGIC_API_TOKEN`
- `/cancel` → `POST https://api.codemagic.io/builds/<buildId>/cancel`
  (remember last started buildId, or list running via `GET /builds?appId=...&status=building`)
- `/status` → `GET /builds?appId=...` → newest build status

Needs in `.env`: `CODEMAGIC_API_TOKEN` (Codemagic → User settings → Integrations → API),
`CODEMAGIC_APP_ID`, workflow ids. Never commit these.

## 3. Multi-APK messages — ✅ DONE (2026-07-02)

Implemented in `find_apk_link()`: parses Slack `<url|label>` links whose label
ends in `.apk` (Codemagic artifact URLs contain no `.apk` themselves — the
original URL-only regex missed real builds entirely!), prefers the `universal`
APK when several are listed, and uses the label as the Telegram filename.
`replay_last_build.py` re-runs the newest artifact message through the pipeline
(recover a missed delivery / test parser changes without posting to Slack).

## 4. Multiple Telegram destinations (groups/channels)

Delivery target is the single `TELEGRAM_CHAT_ID`. To deliver to a group: add bot
to group, get its negative chat id from `getUpdates`, set it. For several targets:
make `TELEGRAM_CHAT_ID` comma-separated and loop in `telegram_send_message` /
`telegram_send_document`. Channels need the bot as admin with post rights.

## 5. Files bigger than 50 MB as real files — ✅ DONE (2026-07-02)

Implemented via **Telethon/MTProto** (no self-hosted Bot API server needed):
bots can upload up to 2 GB over MTProto. `telegram_send_document_mtproto()` in
bot.py, enabled by `TG_API_ID`/`TG_API_HASH` in `.env` (from my.telegram.org).
≤49 MB → fast Bot API path; 49 MB–800 MB → MTProto upload (~2 min for 128 MB);
>800 MB → pretty HTML link fallback (protects the 1 GB server disk).
Session file `mtproto_bot.session` lives next to bot.py. Verified with the real
128 MB `app-dev-release.apk` from build #14.

## 6. Ops debt (not features)

- **Reboot resilience:** no user crontab on alwaysdata. Add a panel
  "Scheduled task" running `run_forever.sh` every 5–10 min (flock makes it
  idempotent) — needs login at admin.alwaysdata.com. Until then, a server reboot
  stops the bot until manually restarted (`setsid nohup ./run_forever.sh`).
- **Codemagic auth fallback:** if artifact links ever return 401/403, set
  `CODEMAGIC_TOKEN` in `.env` (retry with `x-auth-token` is already coded).
- Remember: kill the bot remotely with `pkill -f "[b]ot\.py"` (plain pattern
  kills your own ssh session).
