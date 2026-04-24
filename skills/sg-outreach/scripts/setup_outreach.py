#!/usr/bin/env python3
"""Setup wizard for daily outreach campaigns.

State-machine execution: each invocation reads wip, acts on --user-reply,
sends next prompt via Telegram, exits.

Usage:
    python3 setup_outreach.py --user-id <chat_id> --user-reply "<text>"
    python3 setup_outreach.py --test-only --user-id <chat_id> --test-list <path.csv>
"""

import argparse
import csv
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/root/openclaw-zero-token/lib")
import telegram_notify as tn

USER_BASE = "/root/.openclaw/workspace/outreach"
ACCEPT_WORDS = {"confirm", "confirmed", "yes", "y", "looks good", "received", "go"}
REJECT_WORDS = {"abort", "cancel", "no", "stop", "n"}
SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR = SCRIPT_DIR.parent
GLOBAL_SMTP_CONFIG = SKILL_DIR / ".workspace_smtp_config.json"


def _user_dir(chat_id: str) -> Path:
    return Path(USER_BASE) / f"user_{chat_id}"


def _wip_path(chat_id: str) -> Path:
    return _user_dir(chat_id) / "active_campaign.json.wip"


def _load_wip(chat_id: str) -> dict:
    path = _wip_path(chat_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"step": 0, "chat_id": chat_id}


def _save_wip(chat_id: str, data: dict):
    path = _wip_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _notify(chat_id: str, msg: str):
    tn.send_message(chat_id, msg)
    print(msg)


def _notify_codeblock(chat_id: str, msg: str):
    tn.send_codeblock(chat_id, msg)
    print(msg)


def resolve_smtp_config(chat_id: str) -> Path:
    """Return per-user config if exists, else global."""
    user_cfg = _user_dir(chat_id) / ".workspace_smtp_config.json"
    if user_cfg.exists():
        return user_cfg
    return GLOBAL_SMTP_CONFIG


def _dns_preflight(domain: str) -> dict:
    import dns.resolver
    result = {"spf": False, "dkim": False, "dmarc": False, "warnings": []}
    try:
        answers = dns.resolver.resolve(domain, "TXT")
        for r in answers:
            txt = str(r).lower()
            if "v=spf1" in txt:
                result["spf"] = True
    except Exception:
        pass
    try:
        answers = dns.resolver.resolve(f"default._domainkey.{domain}", "TXT")
        result["dkim"] = True
    except Exception:
        pass
    try:
        answers = dns.resolver.resolve(f"_dmarc.{domain}", "TXT")
        for r in answers:
            if "v=dmarc1" in str(r).lower():
                result["dmarc"] = True
    except Exception:
        pass
    if not result["spf"]:
        result["warnings"].append("SPF missing — emails may land in spam")
    if not result["dkim"]:
        result["warnings"].append("DKIM missing — consider adding default._domainkey")
    if not result["dmarc"]:
        result["warnings"].append("DMARC missing — consider adding _dmarc record")
    return result


def _register_crontab(chat_id: str, cron_expr: str, tz: str, enable_unsub: bool = False):
    marker = f"mirae-daily-send-{chat_id}"
    begin = f"# BEGIN {marker}"
    end = f"# END {marker}"
    script = "/root/openclaw-zero-token/skills/sg-outreach/scripts/daily_outreach.sh"
    user_dir = _user_dir(chat_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # Read existing crontab
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = res.stdout.splitlines() if res.returncode == 0 else []

    # Remove any existing block for this chat_id
    new_lines = []
    inside = False
    for line in lines:
        s = line.strip()
        if s == begin:
            inside = True
            continue
        if s == end:
            inside = False
            continue
        if not inside:
            new_lines.append(line)

    cron_line = f"{cron_expr} TZ={tz} TELEGRAM_CHAT_ID={chat_id} /bin/bash {script} --user-id {chat_id} >> {user_dir}/cron.log 2>&1"
    new_lines.append(begin)
    new_lines.append(cron_line)
    new_lines.append(end)

    if enable_unsub:
        unsub_marker = f"mirae-unsub-sweep-{chat_id}"
        unsub_begin = f"# BEGIN {unsub_marker}"
        unsub_end = f"# END {unsub_marker}"
        # Strip old unsub block if any
        filtered = []
        inside = False
        for line in new_lines:
            s = line.strip()
            if s == unsub_begin:
                inside = True
                continue
            if s == unsub_end:
                inside = False
                continue
            if not inside:
                filtered.append(line)
        new_lines = filtered
        unsub_line = f"0 9 * * 0 TZ={tz} TELEGRAM_CHAT_ID={chat_id} /usr/bin/python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/process_unsubscribes.py --user-id {chat_id} >> {user_dir}/unsub_sweep.log 2>&1"
        new_lines.append(unsub_begin)
        new_lines.append(unsub_line)
        new_lines.append(unsub_end)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".crontab") as f:
        f.write("\n".join(new_lines) + "\n")
        tmp = f.name
    subprocess.run(["crontab", tmp], check=True)
    os.unlink(tmp)


def _most_recent_upload() -> str:
    upload_dir = Path("/root/.openclaw/workspace/leads/uploads")
    files = sorted(upload_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ""


def _run_sequences(user_dir: Path, sender: dict, source_csv: str) -> str:
    seq_path = user_dir / "sequences.csv"
    gen_cmd = [
        sys.executable, str(SKILL_DIR / "scripts" / "generate_sequences.py"),
        source_csv,
        "--sender-name", sender["sender_name"],
        "--sender-title", sender.get("sender_title", "Director"),
        "--sender-company", sender.get("sender_company", "Mirae Advisory"),
        "--sender-email", sender.get("sender_email", ""),
        "--output", str(seq_path),
        "--skip-history-check",
    ]
    subprocess.run(gen_cmd, check=True)
    return str(seq_path)


def _validate(seq_path: str):
    subprocess.run([
        sys.executable, str(SKILL_DIR / "scripts" / "validate_sequences.py"),
        "--sequences", seq_path,
    ], check=True)


def _compliance_audit(seq_path: str, sender_name: str) -> list:
    address_kw = os.environ.get("COMPLIANCE_ADDRESS_KEYWORD", "Singapore")
    errors = []
    with open(seq_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows, 1):
        body = row.get("body", "")
        if sender_name not in body:
            errors.append(f"Row {i}: sender_name '{sender_name}' not in body")
        if "unsubscribe" not in body.lower():
            errors.append(f"Row {i}: unsubscribe missing from body")
        if address_kw.lower() not in body.lower():
            errors.append(f"Row {i}: address keyword '{address_kw}' not in body")
    return errors


def _send_test_email(chat_id: str, test_email: str, seq_path: str, config_path: Path):
    # Create a 1-row temp sequences file targeting the test email
    with open(seq_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("No sequences to test")
    test_row = dict(rows[0])
    test_row["to_email"] = test_email
    test_row["to_name"] = "Test Recipient"
    test_row["send_delay_days"] = "0"
    test_row["email_number"] = "1"
    test_row["status"] = "pending"
    test_row["sent_at"] = ""
    test_row["message_id"] = ""

    tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(tmp, fieldnames=list(test_row.keys()))
    writer.writeheader()
    writer.writerow(test_row)
    tmp.close()

    try:
        cmd = [
            sys.executable, str(SKILL_DIR / "scripts" / "workspace_smtp_sender.py"),
            "--sequences", tmp.name,
            "--daily-limit", "1",
            "--state-file", str(_user_dir(chat_id) / ".outreach_state.json"),
        ]
        if config_path != GLOBAL_SMTP_CONFIG:
            cmd += ["--config-file", str(config_path)]
        subprocess.run(cmd, check=True)
    finally:
        os.unlink(tmp.name)


class Wizard:
    def __init__(self, chat_id: str, reply: str = "", test_only: bool = False, test_list: str = ""):
        self.chat_id = chat_id
        self.reply = reply.strip()
        self.test_only = test_only
        self.test_list = test_list
        self.user_dir = _user_dir(chat_id)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.wip = _load_wip(chat_id)
        self.step = self.wip.get("step", 0)
        self.awaiting = self.wip.get("awaiting", "")

    def run(self):
        if self.test_only:
            return self._run_test_only()

        # Handle restart command
        if self.reply.lower() in ("restart setup", "restart outreach"):
            _wip_path(self.chat_id).unlink(missing_ok=True)
            _notify(self.chat_id, "🔄 Setup restarted from step 1.")
            self.wip = {"step": 0, "chat_id": self.chat_id}
            self.step = 0
            self.awaiting = ""

        # If we were awaiting a reply, process it first
        if self.awaiting and self.reply:
            ok, err = self._process_reply()
            if not ok:
                _notify(self.chat_id, f"❌ {err}\nPlease reply with a valid answer.")
                return
            self.step += 1
            self.awaiting = ""
            self.wip["step"] = self.step
            _save_wip(self.chat_id, self.wip)

        # Now run the current step to send the next prompt
        while True:
            result = self._run_step()
            if result == "done":
                break
            elif result == "wait":
                break
            elif result == "next":
                self.step += 1
                self.wip["step"] = self.step
                _save_wip(self.chat_id, self.wip)
            else:
                break

    def _process_reply(self) -> tuple[bool, str]:
        field = self.awaiting
        reply = self.reply

        if field == "sender_name":
            if len(reply) < 2:
                return False, "Name too short."
            self.wip["sender_name"] = reply
            return True, ""

        if field == "sender_title":
            self.wip["sender_title"] = reply or "Director"
            return True, ""

        if field == "sender_email":
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", reply):
                return False, "Invalid email format."
            self.wip["sender_email"] = reply
            return True, ""

        if field == "sender_company":
            self.wip["sender_company"] = reply or "Mirae Advisory"
            return True, ""

        if field == "smtp_choice":
            lowered = reply.lower()
            if lowered in ("byo", "no", "n"):
                self.wip["smtp_choice"] = "byo"
                self.wip["smtp_byo_step"] = 0
            else:
                self.wip["smtp_choice"] = "shared"
            return True, ""

        if field == "smtp_host":
            self.wip["smtp_host"] = reply
            return True, ""

        if field == "smtp_port":
            try:
                port = int(reply)
                if not (1 <= port <= 65535):
                    raise ValueError
            except ValueError:
                return False, "Invalid port number."
            self.wip["smtp_port"] = port
            return True, ""

        if field == "smtp_user":
            self.wip["smtp_user"] = reply
            return True, ""

        if field == "smtp_password":
            self.wip["smtp_password"] = reply
            # Test auth immediately
            try:
                host = self.wip.get("smtp_host", "")
                port = int(self.wip.get("smtp_port", 587))
                server = smtplib.SMTP(host, port, timeout=15)
                server.ehlo()
                server.starttls()
                server.login(self.wip["smtp_user"], reply)
                server.quit()
            except Exception as e:
                return False, f"SMTP auth failed: {e}"
            # Save per-user config
            cfg = {
                "smtp_host": self.wip["smtp_host"],
                "smtp_port": self.wip["smtp_port"],
                "email": self.wip["smtp_user"],
                "app_password": reply,
            }
            with open(self.user_dir / ".workspace_smtp_config.json", "w") as f:
                json.dump(cfg, f, indent=2)
            return True, ""

        if field == "pdpa_consent":
            if reply.lower() not in ACCEPT_WORDS:
                return False, "PDPA consent required. Reply 'confirmed' to proceed or 'abort' to cancel."
            self.wip["pdpa_consent"] = True
            self.wip["consent_confirmed_at"] = datetime.now().isoformat()
            return True, ""

        if field == "list_path":
            path = reply or _most_recent_upload()
            if not path or not os.path.exists(path):
                return False, f"File not found: {path}"
            self.wip["source_csv"] = path
            return True, ""

        if field == "dry_run_confirm":
            if reply.lower() in REJECT_WORDS:
                _notify(self.chat_id, "Setup aborted. Run 'setup outreach' to restart.")
                _wip_path(self.chat_id).unlink(missing_ok=True)
                return True, ""
            if reply.lower() not in ACCEPT_WORDS:
                return False, "Reply 'looks good' to continue or 'abort' to cancel."
            return True, ""

        if field == "live_test_confirm":
            if reply.lower() in REJECT_WORDS:
                _notify(self.chat_id, "Setup aborted. Run 'setup outreach' to restart.")
                _wip_path(self.chat_id).unlink(missing_ok=True)
                return True, ""
            if reply.lower() not in ACCEPT_WORDS:
                return False, "Reply 'received' after checking your inbox, or 'not received' to retry."
            return True, ""

        if field == "enable_unsub_sweep":
            self.wip["enable_unsub_sweep"] = reply.lower() in ACCEPT_WORDS
            return True, ""

        return True, ""

    def _run_step(self) -> str:
        step = self.step
        wip = self.wip

        if step == 0:
            _notify(self.chat_id, "🚀 *Setup Outreach* — Let's configure your daily email campaign.\nStep 1/16: What sender name should I use? (e.g., 'Dexter Ng')")
            self.awaiting = "sender_name"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 1:
            _notify(self.chat_id, f"Step 2/16: What is your job title? (default: Director)")
            self.awaiting = "sender_title"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 2:
            _notify(self.chat_id, f"Step 3/16: What is your sending email address? (must match your SMTP domain)")
            self.awaiting = "sender_email"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 3:
            _notify(self.chat_id, f"Step 4/16: What company name should appear in the signature? (default: Mirae Advisory)")
            self.awaiting = "sender_company"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 4:
            _notify(self.chat_id, f"Step 5/16: Use shared Mirae SMTP? Reply 'yes' (default) or 'byo' to bring your own.")
            self.awaiting = "smtp_choice"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 5:
            if wip.get("smtp_choice") == "byo":
                _notify(self.chat_id, f"Step 6/16 (BYO): SMTP host? (e.g., smtp.gmail.com)")
                self.awaiting = "smtp_host"
                wip["awaiting"] = self.awaiting
                _save_wip(self.chat_id, wip)
                return "wait"
            return "next"

        if step == 6:
            if wip.get("smtp_choice") == "byo":
                _notify(self.chat_id, f"Step 7/16 (BYO): SMTP port? (e.g., 587)")
                self.awaiting = "smtp_port"
                wip["awaiting"] = self.awaiting
                _save_wip(self.chat_id, wip)
                return "wait"
            return "next"

        if step == 7:
            if wip.get("smtp_choice") == "byo":
                _notify(self.chat_id, f"Step 8/16 (BYO): SMTP username?")
                self.awaiting = "smtp_user"
                wip["awaiting"] = self.awaiting
                _save_wip(self.chat_id, wip)
                return "wait"
            return "next"

        if step == 8:
            if wip.get("smtp_choice") == "byo":
                _notify(self.chat_id, f"Step 9/16 (BYO): SMTP app password?")
                self.awaiting = "smtp_password"
                wip["awaiting"] = self.awaiting
                _save_wip(self.chat_id, wip)
                return "wait"
            return "next"

        if step == 9:
            domain = wip.get("sender_email", "").split("@")[-1]
            dns = _dns_preflight(domain)
            score = sum([dns["spf"], dns["dkim"], dns["dmarc"]])
            msg = f"Step 10/16: DNS preflight for *{domain}*\nSPF: {'✅' if dns['spf'] else '❌'} | DKIM: {'✅' if dns['dkim'] else '❌'} | DMARC: {'✅' if dns['dmarc'] else '❌'}\nScore: {score}/3"
            if dns["warnings"]:
                msg += "\n⚠️ " + "\n⚠️ ".join(dns["warnings"])
            if not dns["spf"]:
                msg += "\n❌ SPF is required. Fix DNS before proceeding, or reply 'skip' to override (not recommended)."
            _notify(self.chat_id, msg)
            if not dns["spf"]:
                self.awaiting = "dns_override"
                wip["awaiting"] = self.awaiting
                _save_wip(self.chat_id, wip)
                return "wait"
            return "next"

        if step == 10:
            _notify(self.chat_id, "Step 11/16: *PDPA Consent*\nDo all leads in this list have documented consent for email marketing under Singapore PDPA?\nReply 'confirmed' to proceed or 'abort' to cancel.")
            self.awaiting = "pdpa_consent"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 11:
            recent = _most_recent_upload()
            _notify(self.chat_id, f"Step 12/16: Lead list selection.\nMost recent upload: `{recent or 'none found'}`\nReply with a file path, or 'ok' to use the most recent.")
            self.awaiting = "list_path"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 12:
            source = wip.get("source_csv", "")
            # Copy to user dir as source_list.csv
            dest = self.user_dir / "source_list.csv"
            shutil.copy2(source, dest)
            sender = {
                "sender_name": wip.get("sender_name", ""),
                "sender_title": wip.get("sender_title", "Director"),
                "sender_company": wip.get("sender_company", "Mirae Advisory"),
                "sender_email": wip.get("sender_email", ""),
            }
            try:
                seq_path = _run_sequences(self.user_dir, sender, str(dest))
                wip["sequences_csv"] = seq_path
                _save_wip(self.chat_id, wip)
            except Exception as e:
                _notify(self.chat_id, f"❌ Sequence generation failed: {e}")
                return "done"

            # Validate
            try:
                _validate(seq_path)
            except Exception as e:
                _notify(self.chat_id, f"❌ Validation failed: {e}")
                return "done"

            # Compliance audit
            errors = _compliance_audit(seq_path, sender["sender_name"])
            if errors:
                _notify(self.chat_id, f"❌ Compliance audit failed:\n" + "\n".join(errors[:5]))
                return "done"

            _notify(self.chat_id, f"✅ Sequences generated and validated. {len(list(csv.DictReader(open(seq_path))))} rows.")
            return "next"

        if step == 13:
            seq_path = wip.get("sequences_csv", "")
            with open(seq_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                preview = f"Subject: {rows[0].get('subject')}\n\nBody:\n{rows[0].get('body')}"
                _notify_codeblock(self.chat_id, preview)
            _notify(self.chat_id, "Step 14/16: *Dry-run preview* above.\nReply 'looks good' to continue or 'abort' to cancel.")
            self.awaiting = "dry_run_confirm"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 14:
            test_email = wip.get("sender_email", "")
            seq_path = wip.get("sequences_csv", "")
            cfg_path = resolve_smtp_config(self.chat_id)
            try:
                _send_test_email(self.chat_id, test_email, seq_path, cfg_path)
                _notify(self.chat_id, f"Step 15/16: *Live self-test* sent to {test_email}.\nCheck your inbox and reply 'received' to confirm, or 'not received' to retry.")
            except Exception as e:
                _notify(self.chat_id, f"⚠️ Self-test failed: {e}\nCheck SMTP config and reply 'retry' to try again, or 'abort' to cancel.")
            self.awaiting = "live_test_confirm"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 15:
            _notify(self.chat_id, "Step 16/16: Enable weekly unsubscribe IMAP sweep? Reply 'yes' or 'no'.")
            self.awaiting = "enable_unsub_sweep"
            wip["awaiting"] = self.awaiting
            _save_wip(self.chat_id, wip)
            return "wait"

        if step == 16:
            # Register crontab
            _register_crontab(
                self.chat_id,
                wip.get("cron_expr", "0 8 * * 1-5"),
                wip.get("cron_tz", "Asia/Singapore"),
                enable_unsub=wip.get("enable_unsub_sweep", False),
            )
            # Finalize
            wip["cron_marker"] = f"mirae-daily-send-{self.chat_id}"
            wip["daily_limit"] = wip.get("daily_limit", 25)
            wip.pop("awaiting", None)
            final_path = self.user_dir / "active_campaign.json"
            with open(final_path, "w", encoding="utf-8") as f:
                json.dump(wip, f, indent=2)
            _wip_path(self.chat_id).unlink(missing_ok=True)
            _notify(self.chat_id, f"🎉 Outreach setup complete!\nDaily limit: {wip['daily_limit']} emails\nNext run: tomorrow 8am SGT\nReply 'next 25' to preview the first batch.")
            return "done"

        _notify(self.chat_id, "Setup complete.")
        return "done"

    def _run_test_only(self):
        if not self.test_list or not os.path.exists(self.test_list):
            _notify(self.chat_id, "❌ --test-list required for test mode.")
            return
        sender = {
            "sender_name": self.wip.get("sender_name", "Test Sender"),
            "sender_title": self.wip.get("sender_title", "Director"),
            "sender_company": self.wip.get("sender_company", "Mirae Advisory"),
            "sender_email": self.wip.get("sender_email", ""),
        }
        try:
            seq_path = _run_sequences(self.user_dir, sender, self.test_list)
            _validate(seq_path)
            errors = _compliance_audit(seq_path, sender["sender_name"])
            if errors:
                _notify(self.chat_id, f"❌ Compliance audit failed:\n" + "\n".join(errors[:5]))
                return
            with open(seq_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                preview = f"Subject: {rows[0].get('subject')}\n\nBody:\n{rows[0].get('body')}"
                _notify_codeblock(self.chat_id, preview)
            _notify(self.chat_id, "✅ Dry-run preview sent. Replying 'looks good' would send one live test email in full setup.")
        except Exception as e:
            _notify(self.chat_id, f"❌ Test failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Setup outreach wizard")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--user-reply", default="", help="User's Telegram reply text")
    parser.add_argument("--test-only", action="store_true")
    parser.add_argument("--test-list", default="", help="Small CSV for test mode")
    args = parser.parse_args()

    env_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if env_chat and env_chat != args.user_id:
        tn.send_message(args.user_id, "❌ Cross-tenant access denied.")
        sys.exit(1)

    wiz = Wizard(args.user_id, reply=args.user_reply, test_only=args.test_only, test_list=args.test_list)
    wiz.run()


if __name__ == "__main__":
    main()
