#!/usr/bin/env python3
"""
Codemagic -> Slack -> Telegram APK forwarder.

Flow:
  1. Codemagic finishes a build and posts a message + APK download link to Slack.
  2. This bot listens to Slack (Socket Mode) for messages containing an .apk link.
  3. It downloads the APK.
  4. It sends the APK file to your Telegram chat.

No public server / webhook URL is required (Socket Mode uses an outbound websocket).
"""

import os
import re
import sys
import html
import json
import shutil
import tempfile
import logging
import threading

import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Load .env from the bot's own directory, regardless of the process CWD
# (the alwaysdata Service supervisor starts us from $HOME).
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("apkbot")

# ---- Config (from environment / .env) ---------------------------------------
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]          # xoxb-...
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]          # xapp-...  (Socket Mode)
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]    # 123456:ABC-...
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]        # your numeric chat id

# Optional: only react to messages in this channel id (e.g. C0123ABCD). Empty = all.
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "").strip()
# Optional: Codemagic API token, used only if a download returns 401/403.
CODEMAGIC_TOKEN = os.environ.get("CODEMAGIC_TOKEN", "").strip()

# Telegram Bot API caps document uploads at 50 MB. Leave headroom.
TELEGRAM_MAX_BYTES = 49 * 1024 * 1024

# Optional MTProto credentials (my.telegram.org) — lets the bot upload files up
# to 2 GB via Telethon instead of falling back to a link. Empty = disabled.
TG_API_ID = os.environ.get("TG_API_ID", "").strip()
TG_API_HASH = os.environ.get("TG_API_HASH", "").strip()
# Stay well under the server's 1 GB disk; beyond this we always send the link.
MTPROTO_MAX_BYTES = 800 * 1024 * 1024

_mtproto_lock = threading.Lock()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def mtproto_available() -> bool:
    return bool(TG_API_ID and TG_API_HASH)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Matches any http(s) URL that contains ".apk" (path or query).
APK_URL_RE = re.compile(r"https?://[^\s<>|\"')]+\.apk[^\s<>|\"')]*", re.IGNORECASE)

# Slack-style link whose LABEL is an .apk filename: <https://…|app-release.apk>.
# Codemagic artifact URLs are signed links with no .apk in the URL itself.
SLACK_APK_LINK_RE = re.compile(r"<(https?://[^|>]+)\|([^>|]*?\.apk)>", re.IGNORECASE)

# "Build 14 1.3.2-dev for app Thompson School finished." (Codemagic fallback text)
BUILD_INFO_RE = re.compile(r"Build #?(\S+)\s+(\S+)?\s*for app (.+?)\s+(?:finished|started|failed)",
                           re.IGNORECASE)
# 'Building "Dev" from branch `main`' / 'Build of "Dev" from branch `main` finished.'
WORKFLOW_RE = re.compile(r'"([^"]+)" from branch')


def extract_build_label(event: dict) -> str | None:
    """Human-friendly build label from a Codemagic Slack message,
    e.g. 'Thompson School Dev #14 1.3.2-dev'."""
    blob = json.dumps(event)
    m = BUILD_INFO_RE.search(blob)
    if not m:
        return None
    num, version, app = m.group(1), m.group(2) or "", m.group(3)
    wf = WORKFLOW_RE.search(blob)
    workflow = wf.group(1) if wf else ""
    parts = [app, workflow, f"#{num}", version]
    # The blob is JSON-escaped; drop any escape backslashes that leak into captures.
    return " ".join(p for p in parts if p).replace("\\", "").strip()

app = App(token=SLACK_BOT_TOKEN, logger=log)


def find_apk_link(event: dict) -> tuple[str, str | None] | None:
    """Scan the whole Slack event payload for an APK link.

    Returns (url, filename_hint) or None. Handles two shapes:
    - Slack links whose label is the filename (Codemagic artifacts):
      <https://api.codemagic.io/artifacts/…signed…|app-release.apk>
      If several APKs are listed, prefers the "universal" one.
    - Plain URLs that contain .apk themselves.
    """
    blob = json.dumps(event)

    labeled = SLACK_APK_LINK_RE.findall(blob)  # [(url, label), ...]
    if labeled:
        for url, label in labeled:
            if "universal" in label.lower():
                return url, label.rsplit("/", 1)[-1]
        url, label = labeled[0]
        return url, label.rsplit("/", 1)[-1]

    m = APK_URL_RE.search(blob)
    if m:
        return m.group(0), None
    return None


class ApkTooLarge(Exception):
    """Raised when the APK exceeds Telegram's upload limit — no point downloading it."""
    def __init__(self, size: int):
        self.size = size


def download_apk(url: str, name_hint: str | None = None) -> tuple[str, int, str]:
    """Download the APK to a temp file. Returns (path, size_bytes, filename)."""
    headers = {}

    def _stream(req_headers):
        return requests.get(url, headers=req_headers, stream=True, timeout=120,
                            allow_redirects=True)

    resp = _stream(headers)
    if resp.status_code in (401, 403) and CODEMAGIC_TOKEN:
        log.info("Got %s, retrying with Codemagic token header", resp.status_code)
        resp.close()
        resp = _stream({"x-auth-token": CODEMAGIC_TOKEN})
    resp.raise_for_status()

    # Don't waste bandwidth/disk on files we can't deliver anyway.
    cap = MTPROTO_MAX_BYTES if mtproto_available() else TELEGRAM_MAX_BYTES
    size_hint = int(resp.headers.get("Content-Length") or 0)
    if size_hint > cap:
        resp.close()
        raise ApkTooLarge(size_hint)

    # Derive a filename: prefer the Slack link label (real artifact name).
    name = name_hint or url.split("?")[0].rstrip("/").split("/")[-1] or "app.apk"
    if not name.lower().endswith(".apk"):
        name += ".apk"

    fd, path = tempfile.mkstemp(suffix="_" + name)
    size = 0
    with os.fdopen(fd, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            if chunk:
                f.write(chunk)
                size += len(chunk)
                # No Content-Length header and the file keeps growing past the cap.
                if size > cap:
                    resp.close()
                    os.remove(path)
                    raise ApkTooLarge(size)
    resp.close()
    log.info("Downloaded %s (%.1f MB)", name, size / 1024 / 1024)
    return path, size, name


def telegram_send_message(text: str, parse_mode: str | None = None) -> None:
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        data["parse_mode"] = parse_mode
    r = requests.post(f"{TELEGRAM_API}/sendMessage", data=data, timeout=30)
    r.raise_for_status()


def telegram_send_document(path: str, caption: str, filename: str | None = None) -> None:
    with open(path, "rb") as f:
        r = requests.post(
            f"{TELEGRAM_API}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"document": (filename or os.path.basename(path), f, "application/vnd.android.package-archive")},
            timeout=600,
        )
    if not r.ok:
        log.error("Telegram error: %s", r.text)
    r.raise_for_status()


def telegram_send_document_mtproto(path: str, caption: str, filename: str) -> None:
    """Upload a big file (up to ~2 GB) via MTProto using the bot's own identity."""
    import asyncio
    from telethon import TelegramClient

    # Telethon uses the file's on-disk name; give it the real artifact name.
    named = os.path.join(os.path.dirname(path), filename)
    if named != path:
        shutil.move(path, named)

    async def _send():
        client = TelegramClient(os.path.join(BASE_DIR, "mtproto_bot"),
                                int(TG_API_ID), TG_API_HASH)
        await client.start(bot_token=TELEGRAM_BOT_TOKEN)
        try:
            await client.send_file(int(TELEGRAM_CHAT_ID), named,
                                   caption=caption, force_document=True)
        finally:
            await client.disconnect()

    try:
        with _mtproto_lock:
            asyncio.run(_send())
    finally:
        try:
            os.remove(named)
        except OSError:
            pass


def link_message(url: str, name: str | None, label: str | None, size_txt: str) -> str:
    title = html.escape(label or "New APK build")
    fname = html.escape(name or "download")
    return (f"📦 <b>{title}</b>\n"
            f'⬇️ <a href="{html.escape(url, quote=True)}">{fname}</a> ({size_txt})\n'
            f"<i>Codemagic link — expires in ~1 week</i>")


def handle_apk(url: str, name_hint: str | None = None, label: str | None = None) -> None:
    max_bytes = MTPROTO_MAX_BYTES if mtproto_available() else TELEGRAM_MAX_BYTES
    try:
        path, size, name = download_apk(url, name_hint)
    except ApkTooLarge as e:
        size_txt = f"{e.size / 1024 / 1024:.1f} MB" if e.size else "large"
        log.info("APK too large (%s, cap %.0f MB), sending link instead",
                 size_txt, max_bytes / 1024 / 1024)
        telegram_send_message(link_message(url, name_hint, label, size_txt), parse_mode="HTML")
        return
    except Exception as e:
        log.exception("Download failed")
        telegram_send_message(f"⚠️ Couldn't download APK.\nLink: {url}\nError: {e}")
        return

    caption = f"📦 {label}" if label else "📦 New APK from Codemagic"
    size_mb = size / 1024 / 1024
    try:
        if size <= TELEGRAM_MAX_BYTES:
            telegram_send_document(path, caption=caption, filename=name)
            log.info("Sent APK to Telegram chat %s", TELEGRAM_CHAT_ID)
        elif mtproto_available():
            log.info("Uploading %.1f MB via MTProto (this can take a few minutes)…", size_mb)
            telegram_send_document_mtproto(path, caption, name)
            path = None  # mtproto helper owns/removes the file
            log.info("Sent big APK via MTProto to chat %s", TELEGRAM_CHAT_ID)
        else:
            telegram_send_message(link_message(url, name, label, f"{size_mb:.1f} MB"),
                                  parse_mode="HTML")
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


@app.event("message")
def on_message(event, logger):
    # Ignore edits, deletes, bot-channel-join, etc. — but DO allow bot_message
    # (Codemagic posts as a bot/integration).
    subtype = event.get("subtype")
    if subtype not in (None, "bot_message", "file_share"):
        return
    if SLACK_CHANNEL_ID and event.get("channel") != SLACK_CHANNEL_ID:
        return

    link = find_apk_link(event)
    if not link:
        return
    url, name_hint = link
    label = extract_build_label(event)
    log.info("Found APK link in Slack message: %s (name: %s, build: %s)",
             url[:100], name_hint or "from URL", label or "?")
    handle_apk(url, name_hint, label)


def main():
    missing = [k for k in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
                           "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(k)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        sys.exit(1)
    log.info("Starting Codemagic→Slack→Telegram APK bot (Socket Mode)…")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()


if __name__ == "__main__":
    main()
