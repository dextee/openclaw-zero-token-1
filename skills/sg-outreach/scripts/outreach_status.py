#!/usr/bin/env python3
"""Outreach status and reporting CLI.

Usage:
    python3 outreach_status.py --status --user-id <chat_id>
    python3 outreach_status.py --preview-next 25 --user-id <chat_id> --notify-chat-id <chat_id>
    python3 outreach_status.py --sent today --user-id <chat_id>
    python3 outreach_status.py --show-failures --user-id <chat_id>
    python3 outreach_status.py --send-report weekly --user-id <chat_id>
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/root/openclaw-zero-token/lib")
import telegram_notify as tn

USER_BASE = "/root/.openclaw/workspace/outreach"


def _user_dir(chat_id: str) -> str:
    return os.path.join(USER_BASE, f"user_{chat_id}")


def _load_campaign(chat_id: str) -> dict:
    path = os.path.join(_user_dir(chat_id), "active_campaign.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_sequences(chat_id: str) -> list:
    path = os.path.join(_user_dir(chat_id), "sequences.csv")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_runs_log(chat_id: str) -> list:
    path = os.path.join(_user_dir(chat_id), "runs.log")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _next_run_sgt(cron_expr: str, tz: str = "Asia/Singapore") -> str:
    try:
        from croniter import croniter
        import pytz
        tz_obj = pytz.timezone(tz)
        now = datetime.now(tz_obj)
        itr = croniter(cron_expr, now)
        nxt = itr.get_next(datetime)
        return nxt.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return "unknown"


def _parse_run_line(line: str) -> dict:
    # Format: 2026-04-24T21:00:00+02:00|trigger=scheduled|sent=25|failed=0|skipped=0|duration_s=120|rc=0
    parts = line.split("|")
    result = {"raw": line}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            result[k] = v
    return result


def status(chat_id: str) -> str:
    campaign = _load_campaign(chat_id)
    seqs = _load_sequences(chat_id)
    runs = _load_runs_log(chat_id)
    user_dir = _user_dir(chat_id)

    active = os.path.exists(os.path.join(user_dir, "active_campaign.json"))
    paused = os.path.exists(os.path.join(user_dir, "paused.flag"))

    total_sent = sum(1 for s in seqs if s.get("status") == "sent")
    total_failed = sum(1 for s in seqs if s.get("status") == "failed")
    pending = [s for s in seqs if s.get("status") in ("", "pending")]

    last_run = "never"
    if runs:
        last = _parse_run_line(runs[-1])
        last_run = last.get("raw", "").split("|")[0]

    next_run = "unknown"
    cron_expr = campaign.get("cron_expr", "")
    if cron_expr:
        next_run = _next_run_sgt(cron_expr)

    failures_7d = 0
    cutoff = datetime.now() - timedelta(days=7)
    for line in runs:
        try:
            ts_str = line.split("|")[0]
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                parsed = _parse_run_line(line)
                failures_7d += int(parsed.get("failed", 0))
        except Exception:
            continue

    lines = [
        f"📬 Outreach Status",
        f"",
        f"Active: {'yes' if active else 'no'}",
        f"Paused: {'yes' if paused else 'no'}",
        f"Daily limit: {campaign.get('daily_limit', 'unset')}",
        f"",
        f"Sent: {total_sent} | Failed: {total_failed} | Pending: {len(pending)}",
        f"Last run: {last_run}",
        f"Next run: {next_run}",
        f"Failures (7d): {failures_7d}",
    ]
    return "\n".join(lines)


def preview_next(chat_id: str, n: int = 25) -> str:
    seqs = _load_sequences(chat_id)
    pending = [s for s in seqs if s.get("status") in ("", "pending") and int(s.get("send_delay_days", 0)) == 0]
    preview = pending[:n]
    if not preview:
        return "No pending emails with send_delay_days=0."
    lines = [f"{'Company':<30} | {'Email':<35} | {'DM':<25} | Subject"]
    lines.append("-" * 120)
    for s in preview:
        co = (s.get("company_name") or "")[:28]
        em = (s.get("to_email") or "")[:33]
        dm = (s.get("to_name") or "")[:23]
        subj = (s.get("subject") or "")[:40]
        lines.append(f"{co:<30} | {em:<35} | {dm:<25} | {subj}")
    return "\n".join(lines)


def sent_on(chat_id: str, day: str) -> str:
    seqs = _load_sequences(chat_id)
    today_str = datetime.now().strftime("%Y-%m-%d")
    if day == "yesterday":
        target = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        target = today_str

    sent = [s for s in seqs if s.get("status") == "sent" and s.get("sent_at", "").startswith(target)]
    if not sent:
        return f"No emails sent on {target}."
    lines = [f"Sent on {target} ({len(sent)} emails):"]
    for s in sent:
        lines.append(f"  {s.get('to_email')} | {s.get('company_name')} | msg_id={s.get('message_id', 'n/a')}")
    return "\n".join(lines)


def show_failures(chat_id: str, limit: int = 20) -> str:
    seqs = _load_sequences(chat_id)
    fails = [s for s in seqs if s.get("status") == "failed"][-limit:]
    if not fails:
        return "No failed emails."
    lines = [f"Last {len(fails)} failures:"]
    for s in fails:
        lines.append(f"  {s.get('to_email')} | {s.get('company_name')} | reason={s.get('status', 'failed')}")
    return "\n".join(lines)


def send_report(chat_id: str, period: str = "weekly") -> str:
    seqs = _load_sequences(chat_id)
    total = len(seqs)
    sent = sum(1 for s in seqs if s.get("status") == "sent")
    failed = sum(1 for s in seqs if s.get("status") == "failed")
    pending = sum(1 for s in seqs if s.get("status") in ("", "pending"))
    suppressed = sum(1 for s in seqs if "skipped" in s.get("status", ""))
    pct = (sent / total * 100) if total else 0
    lines = [
        f"📊 {period.title()} Report",
        f"",
        f"Total sequences: {total}",
        f"Sent: {sent} ({pct:.1f}%)",
        f"Failed: {failed}",
        f"Pending: {pending}",
        f"Suppressed/Skipped: {suppressed}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Outreach status CLI")
    parser.add_argument("--user-id", required=True, help="Telegram chat ID")
    parser.add_argument("--status", action="store_true", help="Show campaign status")
    parser.add_argument("--preview-next", type=int, default=0, help="Show next N pending emails")
    parser.add_argument("--sent", choices=["today", "yesterday"], help="Show sent emails for day")
    parser.add_argument("--show-failures", action="store_true", help="Show recent failures")
    parser.add_argument("--send-report", choices=["daily", "weekly"], help="Generate rollup report")
    parser.add_argument("--notify-chat-id", default="", help="Send output to Telegram chat ID instead of stdout")
    args = parser.parse_args()

    # Scope check
    env_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if env_chat and env_chat != args.user_id:
        msg = f"Cross-tenant access denied. You are {env_chat}, requested {args.user_id}."
        if args.notify_chat_id:
            tn.send_message(args.notify_chat_id, msg)
        else:
            print(msg)
        sys.exit(1)

    output = ""
    if args.status:
        output = status(args.user_id)
    elif args.preview_next > 0:
        output = preview_next(args.user_id, args.preview_next)
    elif args.sent:
        output = sent_on(args.user_id, args.sent)
    elif args.show_failures:
        output = show_failures(args.user_id)
    elif args.send_report:
        output = send_report(args.user_id, args.send_report)
    else:
        output = status(args.user_id)

    if args.notify_chat_id:
        # Tabular outputs go as codeblock; plain text as markdown
        if args.preview_next > 0 or args.show_failures:
            tn.send_codeblock(args.notify_chat_id, output)
        else:
            tn.send_message(args.notify_chat_id, output)
    else:
        print(output)


if __name__ == "__main__":
    main()
