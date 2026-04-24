#!/usr/bin/env python3
"""Shared Python Telegram notifier for MiraeAd outreach scripts.

Usage:
    from telegram_notify import send_message, send_codeblock
    send_message(chat_id, "Hello", parse_mode="Markdown")
    send_codeblock(chat_id, "multiline\ncontent")
"""

import os
import re
import sys
from pathlib import Path


def _get_bot_token() -> str:
    """Read TELEGRAM_BOT_TOKEN from .env file."""
    env_path = Path("/root/openclaw-zero-token/.env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def send_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> dict:
    """Send a plain text or Markdown message to a Telegram chat."""
    token = _get_bot_token()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not found"}
    if not chat_id:
        return {"ok": False, "error": "chat_id empty"}

    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        resp = requests.post(url, data=payload, timeout=15)
        data = resp.json()
        return {"ok": data.get("ok", False), "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_codeblock(chat_id: str, text: str) -> dict:
    """Send text wrapped in triple backticks so Telegram renders it as monospace."""
    # Escape backticks inside the message to avoid breaking Markdown
    safe = text.replace("```", "`\u200B`\u200B`")
    wrapped = f"```{safe}\n```"
    return send_message(chat_id, wrapped, parse_mode="Markdown")


def send_plain(chat_id: str, text: str) -> dict:
    """Send plain text without Markdown parsing."""
    return send_message(chat_id, text, parse_mode="")


if __name__ == "__main__":
    # Quick CLI test: python3 telegram_notify.py <chat_id> <msg>
    if len(sys.argv) >= 3:
        result = send_message(sys.argv[1], sys.argv[2])
        print(result)
    else:
        print("Usage: python3 telegram_notify.py <chat_id> <message>")
