#!/usr/bin/env python3
"""Outreach control CLI — pause, resume, stop, send-now, etc.

Usage:
    python3 outreach_control.py --pause --user-id <chat_id>
    python3 outreach_control.py --resume --user-id <chat_id>
    python3 outreach_control.py --stop --user-id <chat_id>
    python3 outreach_control.py --send-now --user-id <chat_id>
    python3 outreach_control.py --change-limit 25 --user-id <chat_id>
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, "/root/openclaw-zero-token/lib")
import telegram_notify as tn

USER_BASE = "/root/.openclaw/workspace/outreach"
PENDING_ACTION_TTL_SECONDS = 300


def _user_dir(chat_id: str) -> str:
    return os.path.join(USER_BASE, f"user_{chat_id}")


def _load_campaign(chat_id: str) -> dict:
    path = os.path.join(_user_dir(chat_id), "active_campaign.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_campaign(chat_id: str, data: dict):
    path = os.path.join(_user_dir(chat_id), "active_campaign.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _marker(chat_id: str) -> str:
    return f"mirae-daily-send-{chat_id}"


def _crontab_lines() -> list[str]:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def _write_crontab(lines: list[str]) -> bool:
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".crontab") as f:
        f.write("\n".join(lines) + "\n")
        tmp = f.name
    result = subprocess.run(["crontab", tmp], capture_output=True, text=True)
    os.unlink(tmp)
    return result.returncode == 0


def _rewrite_crontab(chat_id: str, action: str) -> tuple[bool, str]:
    """action: 'pause' | 'resume' | 'remove'"""
    marker = _marker(chat_id)
    begin = f"# BEGIN {marker}"
    end = f"# END {marker}"
    lines = _crontab_lines()
    new_lines = []
    inside = False
    changed = False

    for line in lines:
        stripped = line.strip()
        if stripped == begin:
            inside = True
            new_lines.append(line)
            continue
        if stripped == end:
            inside = False
            new_lines.append(line)
            continue
        if inside:
            if action == "pause":
                if not line.strip().startswith("#") and line.strip():
                    new_lines.append("# " + line)
                    changed = True
                else:
                    new_lines.append(line)
            elif action == "resume":
                if line.strip().startswith("# "):
                    new_lines.append(line[2:])
                    changed = True
                else:
                    new_lines.append(line)
            elif action == "remove":
                changed = True
                continue
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if action == "remove":
        # Also strip dangling markers if the block was already malformed
        new_lines = [l for l in new_lines if l.strip() not in (begin, end)]

    ok = _write_crontab(new_lines)
    if not ok:
        return False, "crontab write failed"
    if not changed and action != "remove":
        return True, f"no change needed ({action})"
    return True, f"crontab {action}d"


def _pending_action_path(chat_id: str) -> str:
    return os.path.join(_user_dir(chat_id), ".pending_action.json")


def _set_pending_action(chat_id: str, action: str, detail: str = ""):
    path = _pending_action_path(chat_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"action": action, "detail": detail, "ts": time.time()}, f)


def _get_pending_action(chat_id: str) -> dict:
    path = _pending_action_path(chat_id)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if time.time() - data.get("ts", 0) > PENDING_ACTION_TTL_SECONDS:
                return {}
            return data
        except Exception:
            return {}


def _clear_pending_action(chat_id: str):
    path = _pending_action_path(chat_id)
    if os.path.exists(path):
        os.remove(path)


def _today_sgt() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _notify(chat_id: str, msg: str):
    tn.send_message(chat_id, msg)
    print(msg)


def main():
    parser = argparse.ArgumentParser(description="Outreach control CLI")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--skip-today", action="store_true")
    parser.add_argument("--retry-today", action="store_true")
    parser.add_argument("--send-now", action="store_true")
    parser.add_argument("--change-sender", default="")
    parser.add_argument("--change-limit", type=int, default=0)
    parser.add_argument("--confirm", action="store_true", help="Confirm destructive action")
    args = parser.parse_args()

    chat_id = args.user_id
    user_dir = _user_dir(chat_id)
    env_chat = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Cross-tenant protection
    if env_chat and env_chat != chat_id:
        msg = f"❌ Cross-tenant access denied."
        _notify(chat_id, msg)
        sys.exit(1)

    campaign = _load_campaign(chat_id)
    if not campaign and not args.stop:
        _notify(chat_id, "❌ No active campaign. Run 'setup outreach' first.")
        sys.exit(1)

    # Destructive actions require two-turn confirmation
    destructive = args.stop or args.change_sender or args.change_limit
    if destructive and not args.confirm:
        pending = _get_pending_action(chat_id)
        if pending.get("action") == ("stop" if args.stop else "change"):
            # User replied with confirmation
            pass
        else:
            action_name = "stop outreach" if args.stop else ("change sender" if args.change_sender else "change limit")
            _set_pending_action(chat_id, "stop" if args.stop else "change")
            _notify(chat_id, f"⚠️ Destructive action: {action_name}.\nReply 'confirm' to proceed or 'cancel' to abort.")
            sys.exit(0)

    _clear_pending_action(chat_id)

    if args.pause:
        ok, msg = _rewrite_crontab(chat_id, "pause")
        flag_path = os.path.join(user_dir, "paused.flag")
        open(flag_path, "a").close()
        _notify(chat_id, f"⏸ Outreach paused. {msg}")
        return

    if args.resume:
        ok, msg = _rewrite_crontab(chat_id, "resume")
        flag_path = os.path.join(user_dir, "paused.flag")
        if os.path.exists(flag_path):
            os.remove(flag_path)
        _notify(chat_id, f"▶️ Outreach resumed. {msg}")
        return

    if args.stop:
        ok, msg = _rewrite_crontab(chat_id, "remove")
        # Archive campaign
        backup_dir = os.path.join(user_dir, "backups", f"stopped_{_today_sgt()}")
        os.makedirs(backup_dir, exist_ok=True)
        camp_path = os.path.join(user_dir, "active_campaign.json")
        if os.path.exists(camp_path):
            os.rename(camp_path, os.path.join(backup_dir, "active_campaign.json"))
        # Clean up flags
        for f in ["paused.flag", ".pending_action.json"]:
            fp = os.path.join(user_dir, f)
            if os.path.exists(fp):
                os.remove(fp)
        _notify(chat_id, f"🛑 Outreach stopped. {msg}")
        return

    if args.skip_today:
        state_path = os.path.join(user_dir, ".outreach_state.json")
        state = {}
        if os.path.exists(state_path):
            with open(state_path, "r") as f:
                state = json.load(f)
        state["last_send_date"] = _today_sgt()
        state["sent_today"] = 0
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
        _notify(chat_id, f"⏭ Today skipped. No emails will be sent until tomorrow.")
        return

    if args.send_now or args.retry_today:
        trigger = "manual" if args.send_now else "retry"
        script = "/root/openclaw-zero-token/skills/sg-outreach/scripts/daily_outreach.sh"
        # Check paused
        if os.path.exists(os.path.join(user_dir, "paused.flag")):
            _notify(chat_id, "⏸ Outreach is paused. Resume first.")
            sys.exit(1)
        # Idempotency: check if already sent today
        state_path = os.path.join(user_dir, ".outreach_state.json")
        state = {}
        if os.path.exists(state_path):
            with open(state_path, "r") as f:
                state = json.load(f)
        if state.get("last_send_date") == _today_sgt() and state.get("sent_today", 0) > 0:
            _notify(chat_id, f"✅ Already sent today ({state['sent_today']} emails). Skipping to avoid duplicates.")
            sys.exit(0)

        _notify(chat_id, f"🚀 Triggering outreach now ({trigger})...")
        rc = subprocess.call(["bash", script, "--user-id", chat_id, "--trigger", trigger])
        sys.exit(rc)

    if args.change_sender:
        campaign["sender_name"] = args.change_sender
        campaign["sequences_needs_regen"] = True
        _save_campaign(chat_id, campaign)
        _notify(chat_id, f"✏️ Sender name changed to '{args.change_sender}'. Regenerate sequences before next send.")
        return

    if args.change_limit:
        limit = args.change_limit
        if not (1 <= limit <= 100):
            _notify(chat_id, f"❌ Limit {limit} out of range. Must be 1–100.")
            sys.exit(1)
        campaign["daily_limit"] = limit
        _save_campaign(chat_id, campaign)
        _notify(chat_id, f"✏️ Daily limit changed to {limit}.")
        return

    _notify(chat_id, "No action specified.")


if __name__ == "__main__":
    main()
