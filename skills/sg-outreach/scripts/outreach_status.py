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

    total = len(seqs)
    total_sent = sum(1 for s in seqs if s.get("status") == "sent")
    total_failed = sum(1 for s in seqs if s.get("status") == "failed")
    pending = [s for s in seqs if s.get("status") in ("", "pending")]
    suppressed = sum(1 for s in seqs if "skipped" in (s.get("status") or "") or "suppress" in (s.get("status") or ""))

    today_sgt = datetime.now().strftime("%Y-%m-%d")
    sent_today = sum(1 for s in seqs if s.get("status") == "sent" and (s.get("sent_at") or "").startswith(today_sgt))

    last_run = "never"
    last_sent = last_failed = "?"
    if runs:
        last = _parse_run_line(runs[-1])
        last_run = last.get("raw", "").split("|")[0][:19]
        last_sent = last.get("sent", "?")
        last_failed = last.get("failed", "?")

    next_run = "unknown"
    cron_expr = campaign.get("cron_expr", "")
    if cron_expr:
        next_run = _next_run_sgt(cron_expr)
    elif active:
        next_run = "next weekday 8am SGT"

    daily_limit = campaign.get("daily_limit", 25)
    seq_csv = campaign.get("sequences_csv", os.path.join(user_dir, "sequences.csv"))
    pct = (total_sent / total * 100) if total else 0

    state_word = "🟢 active" if (active and not paused) else ("⏸ paused" if paused else "⚪ not set up")

    lines = [
        f"📬 Mirae Outreach — Status",
        f"",
        f"State: {state_word}",
        f"Daily limit: {daily_limit} emails",
        f"",
        f"📊 Progress: {total_sent}/{total} sent ({pct:.1f}%)",
        f"  • Sent today: {sent_today}/{daily_limit}",
        f"  • Pending: {len(pending)}",
        f"  • Failed: {total_failed}",
        f"  • Skipped/suppressed: {suppressed}",
        f"",
        f"⏱  Last run: {last_run} ({last_sent} sent, {last_failed} failed)",
        f"⏱  Next run: {next_run}",
        f"",
        f"📂 Tracking file:",
        f"   {seq_csv}",
        f"",
        f"Reply 'view sent' / 'view pending' / 'view failures' to drill in.",
        f"Reply 'menu' for all commands.",
    ]
    return "\n".join(lines)


def show_files(chat_id: str) -> str:
    campaign = _load_campaign(chat_id)
    user_dir = _user_dir(chat_id)
    seqs = _load_sequences(chat_id)

    seq_csv = campaign.get("sequences_csv", os.path.join(user_dir, "sequences.csv"))
    source_list = campaign.get("source_list", os.path.join(user_dir, "source_list.csv"))
    runs_log = os.path.join(user_dir, "runs.log")
    cron_log = os.path.join(user_dir, "cron.log")

    def _info(p):
        if not os.path.exists(p):
            return "  (not yet created)"
        sz = os.path.getsize(p)
        return f"  {sz:,} bytes"

    sent = sum(1 for s in seqs if s.get("status") == "sent")
    pending = sum(1 for s in seqs if s.get("status") in ("", "pending"))

    lines = [
        f"📂 Outreach files",
        f"",
        f"📄 Tracking CSV ({sent} sent, {pending} pending)",
        f"   {seq_csv}",
        _info(seq_csv),
        f"",
        f"📋 Source list (original upload)",
        f"   {source_list}",
        _info(source_list),
        f"",
        f"📝 Run history",
        f"   {runs_log}",
        _info(runs_log),
        f"",
        f"📝 Cron fire log",
        f"   {cron_log}",
        _info(cron_log),
        f"",
        f"To view contents in Telegram, reply:",
        f"  • view sent — emails delivered so far",
        f"  • view pending — emails still queued",
        f"  • view failures — emails that failed",
        f"  • view runs — last 10 cron runs",
        f"",
        f"For the full CSV, copy the path above and download via Files.",
    ]
    return "\n".join(lines)


def view_section(chat_id: str, which: str, limit: int = 25) -> str:
    seqs = _load_sequences(chat_id)
    if which == "sent":
        rows = [s for s in seqs if s.get("status") == "sent"]
        title = f"Sent ({len(rows)} total — showing last {min(limit, len(rows))})"
        rows = rows[-limit:]
    elif which == "pending":
        rows = [s for s in seqs if s.get("status") in ("", "pending")]
        title = f"Pending ({len(rows)} total — showing first {min(limit, len(rows))})"
        rows = rows[:limit]
    elif which == "failures":
        rows = [s for s in seqs if s.get("status") == "failed"]
        title = f"Failures ({len(rows)} total — showing last {min(limit, len(rows))})"
        rows = rows[-limit:]
    else:
        return f"Unknown section: {which}. Use sent / pending / failures."

    if not rows:
        return f"No {which} emails."

    lines = [title, ""]
    for i, s in enumerate(rows, 1):
        co = (s.get("company_name") or "")[:30]
        em = (s.get("to_email") or "")[:38]
        lines.append(f"{i:>2}. {co}")
        lines.append(f"    {em}")
        if which == "sent":
            sent_at = (s.get("sent_at") or "")[:19]
            lines.append(f"    sent: {sent_at}")
        elif which == "failures":
            reason = s.get("status_detail") or s.get("error") or "failed"
            lines.append(f"    reason: {reason}")
    return "\n".join(lines)


def view_runs(chat_id: str, limit: int = 10) -> str:
    runs = _load_runs_log(chat_id)
    if not runs:
        return "No runs yet."
    recent = runs[-limit:]
    lines = [f"Last {len(recent)} runs:", ""]
    for line in recent:
        p = _parse_run_line(line)
        ts = p.get("raw", "").split("|")[0][:19]
        lines.append(f"{ts}  trigger={p.get('trigger','?')}  sent={p.get('sent','?')}  failed={p.get('failed','?')}  rc={p.get('rc','?')}")
    return "\n".join(lines)


def menu() -> str:
    return (
        "📬 *Mirae Outreach — Command Menu*\n"
        "\n"
        "📊 *Status & Progress*\n"
        "  • status — current state, today's progress, next run\n"
        "  • sent today — emails sent today\n"
        "  • sent yesterday — emails sent yesterday\n"
        "  • show failures — recent failed sends\n"
        "  • next 25 — preview tomorrow's batch\n"
        "  • send report — 7-day summary\n"
        "\n"
        "📂 *Files & Records*\n"
        "  • show files — file paths + sizes\n"
        "  • view sent — recent delivered emails\n"
        "  • view pending — what's still queued\n"
        "  • view failures — what failed\n"
        "  • view runs — last 10 cron runs\n"
        "\n"
        "⚙️ *Control*\n"
        "  • pause outreach — stop daily fires\n"
        "  • resume outreach — restart daily fires\n"
        "  • skip today — skip today only\n"
        "  • send now — fire today's batch now\n"
        "  • retry today — re-run today if it failed\n"
        "  • stop outreach — cancel campaign\n"
        "\n"
        "🔧 *Settings*\n"
        "  • change daily limit to N — change cap (1–100)\n"
        "\n"
        "📤 *List Management*\n"
        "  • upload an xlsx file → say \"use this for outreach\"\n"
        "\n"
        "🆘 *Help*\n"
        "  • menu — this menu\n"
        "  • help — this menu"
    )


def preview_next(chat_id: str, n: int = 25) -> str:
    seqs = _load_sequences(chat_id)
    pending = [s for s in seqs if s.get("status") in ("", "pending") and int(s.get("send_delay_days", 0)) == 0]
    preview = pending[:n]
    if not preview:
        return "No pending emails with send_delay_days=0."
    lines = [f"Next {len(preview)} to send:", ""]
    for i, s in enumerate(preview, 1):
        co = (s.get("company_name") or "")[:30]
        em = (s.get("to_email") or "")[:38]
        dm = (s.get("to_name") or "").strip()
        line = f"{i:>2}. {co}"
        if dm:
            line += f" — {dm[:25]}"
        lines.append(line)
        lines.append(f"    {em}")
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
    parser.add_argument("--user-id", required=False, default="", help="Telegram chat ID (not required for --menu)")
    parser.add_argument("--status", action="store_true", help="Show campaign status")
    parser.add_argument("--preview-next", type=int, default=0, help="Show next N pending emails")
    parser.add_argument("--sent", choices=["today", "yesterday"], help="Show sent emails for day")
    parser.add_argument("--show-failures", action="store_true", help="Show recent failures")
    parser.add_argument("--send-report", choices=["daily", "weekly"], help="Generate rollup report")
    parser.add_argument("--show-files", action="store_true", help="Show file paths + sizes")
    parser.add_argument("--view", choices=["sent", "pending", "failures", "runs"], help="Drill into a section")
    parser.add_argument("--menu", action="store_true", help="Show full command menu")
    parser.add_argument("--notify-chat-id", default="", help="Send output to Telegram chat ID instead of stdout")
    args = parser.parse_args()

    # --menu does not require user-id
    if args.menu:
        output = menu()
        if args.notify_chat_id:
            tn.send_message(args.notify_chat_id, output)
        else:
            print(output)
        return

    if not args.user_id:
        print("ERROR: --user-id is required for this command.")
        sys.exit(2)

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
    use_codeblock = False
    if args.status:
        output = status(args.user_id)
    elif args.show_files:
        output = show_files(args.user_id)
    elif args.view:
        if args.view == "runs":
            output = view_runs(args.user_id)
        else:
            output = view_section(args.user_id, args.view)
        use_codeblock = True
    elif args.preview_next > 0:
        output = preview_next(args.user_id, args.preview_next)
        use_codeblock = True
    elif args.sent:
        output = sent_on(args.user_id, args.sent)
        use_codeblock = True
    elif args.show_failures:
        output = show_failures(args.user_id)
        use_codeblock = True
    elif args.send_report:
        output = send_report(args.user_id, args.send_report)
    else:
        output = status(args.user_id)

    if args.notify_chat_id:
        if use_codeblock:
            tn.send_codeblock(args.notify_chat_id, output)
        else:
            tn.send_message(args.notify_chat_id, output)
    else:
        print(output)


if __name__ == "__main__":
    main()
