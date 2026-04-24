#!/usr/bin/env python3
"""SG Email Verifier — Zero-Cost Pipeline.

Verifies emails via DNS MX lookup + SMTP RCPT TO handshake.
No APIs, no credits, no emails sent.

Usage:
    python3 verify_emails.py leads/sg_leads_raw.csv
    python3 verify_emails.py leads/sg_leads_raw.csv --skip-catchall-smtp
    python3 verify_emails.py leads/sg_leads_raw.csv --workers 3 --delay 1.5
"""

import argparse
import csv
import logging
import os
import random
import re
import smtplib
import socket
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import dns.resolver
from colorama import Fore, Style, init as colorama_init
from tqdm import tqdm

colorama_init(autoreset=True)

# ── Logging ──────────────────────────────────────────────────────────────────

os.makedirs("leads", exist_ok=True)

logger = logging.getLogger("sg-verify")
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

file_handler = logging.FileHandler("leads/sg_verify_log.txt", mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

fmt = logging.Formatter("[%(asctime)s] %(levelname)s — %(message)s")
console_handler.setFormatter(fmt)
file_handler.setFormatter(fmt)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# ── Globals ──────────────────────────────────────────────────────────────────

EMAIL_COLS = ("email", "Email", "EMAIL")
DOMAIN_COLS = ("website", "Website", "domain", "Domain")
HOSTING_DOMAINS = ("wix.com", "wordpress.com", "blogspot.com", "weebly.com", "shopify.com")

port25_failures = 0
port25_attempts = 0
port25_lock = threading.Lock()


# ── 1. validate_format ───────────────────────────────────────────────────────

def validate_format(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return False
    local = email.split("@")[0]
    if ".." in local:
        return False
    if local.startswith(".") or local.endswith("."):
        return False
    return True


# ── 2. get_mx_records ────────────────────────────────────────────────────────

def get_mx_records(domain: str, cache: dict) -> list:
    if domain in cache:
        return cache[domain]
    try:
        answers = dns.resolver.resolve(domain, "MX")
        results = sorted([(r.preference, str(r.exchange).rstrip(".")) for r in answers])
        mx_hosts = [h for _, h in results]
        cache[domain] = mx_hosts
        return mx_hosts
    except Exception:
        cache[domain] = []
        return []


# ── 3. detect_mx_provider ────────────────────────────────────────────────────

def detect_mx_provider(mx_hosts: list) -> str:
    if not mx_hosts:
        return "none"
    first = mx_hosts[0].lower()
    if "google" in first or "gmail" in first:
        return "google"
    if "outlook" in first or "protection.microsoft" in first or "mail.protection" in first:
        return "microsoft"
    if "mimecast" in first:
        return "mimecast"
    if "proofpoint" in first:
        return "proofpoint"
    return "custom"


# ── 4. is_catch_all ──────────────────────────────────────────────────────────

def is_catch_all(domain: str, mx_hosts: list, timeout: int = 8) -> bool | None:
    test_addr = f"xverifytest{random.randint(10000000, 99999999)}@{domain}"
    code, _ = smtp_verify(test_addr, mx_hosts, timeout)
    if code == 250 or code == 251:
        return True
    if code in (550, 551, 552, 553):
        return False
    return None


# ── 5. smtp_verify ───────────────────────────────────────────────────────────

def smtp_verify(email: str, mx_hosts: list, timeout: int = 8) -> tuple:
    global port25_failures, port25_attempts
    for host in mx_hosts:
        # Try port 25
        with port25_lock:
            port25_attempts += 1
        try:
            server = smtplib.SMTP(host, timeout=timeout)
            server.ehlo("verify.local")
            server.mail("noreply@verify.local")
            code, msg = server.rcpt(email)
            server.rset()
            server.quit()
            return (code, msg.decode() if isinstance(msg, bytes) else msg)
        except socket.timeout:
            with port25_lock:
                port25_failures += 1
            continue
        except ConnectionRefusedError:
            with port25_lock:
                port25_failures += 1
            continue
        except smtplib.SMTPConnectError:
            with port25_lock:
                port25_failures += 1
            continue
        except smtplib.SMTPServerDisconnected:
            with port25_lock:
                port25_failures += 1
            continue
        except OSError as e:
            if e.errno in (101, 111):
                with port25_lock:
                    port25_failures += 1
                continue
            with port25_lock:
                port25_failures += 1
            return (0, f"Unknown error: {str(e)[:80]}")
        except Exception as e:
            with port25_lock:
                port25_failures += 1
            return (0, f"Unknown error: {str(e)[:80]}")

        # Fallback to port 587
        try:
            server = smtplib.SMTP(host, 587, timeout=timeout)
            server.ehlo("verify.local")
            server.starttls()
            server.ehlo("verify.local")
            server.mail("noreply@verify.local")
            code, msg = server.rcpt(email)
            server.rset()
            server.quit()
            return (code, msg.decode() if isinstance(msg, bytes) else msg)
        except Exception:
            continue

    return (0, "All MX hosts failed")


# ── 6. generate_email_patterns ───────────────────────────────────────────────

def generate_email_patterns(row: dict) -> list:
    domain = None
    for col in DOMAIN_COLS:
        val = row.get(col, "").strip()
        if val:
            domain = val
            break
    if not domain:
        return []

    domain = domain.lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = re.sub(r'^www\.', '', domain)
    domain = re.sub(r'/.*$', '', domain)
    domain = domain.rstrip("/")

    for hd in HOSTING_DOMAINS:
        if domain.endswith(hd):
            return []

    name = row.get("decision_maker_name", "").strip()
    firstname = ""
    lastname = ""
    if name:
        parts = re.sub(r'[^a-zA-Z\s]', '', name).split()
        if parts:
            firstname = parts[0].lower()
        if len(parts) > 1:
            lastname = parts[-1].lower()

    patterns = [
        (f"info@{domain}", "pattern_info"),
        (f"sales@{domain}", "pattern_sales"),
        (f"enquiry@{domain}", "pattern_enquiry"),
        (f"admin@{domain}", "pattern_admin"),
        (f"contact@{domain}", "pattern_contact"),
        (f"hello@{domain}", "pattern_hello"),
        (f"business@{domain}", "pattern_business"),
    ]
    if firstname:
        patterns.append((f"{firstname}@{domain}", "pattern_firstname"))
    if firstname and lastname:
        patterns.append((f"{firstname}.{lastname}@{domain}", "pattern_firstname_lastname"))
        patterns.append((f"{firstname}{lastname}@{domain}", "pattern_fn_ln_concat"))

    return patterns[:10]


# ── 7. compute_confidence ────────────────────────────────────────────────────

def compute_confidence(smtp_code: int, is_catch_all: bool,
                       mx_provider: str, email_source: str) -> int:
    if smtp_code in (250, 251):
        base = 85
    elif smtp_code in (550, 551, 552, 553):
        base = 0
    elif 400 <= smtp_code < 500:
        base = 40
    elif smtp_code in (408, 421):
        base = 30
    else:
        base = 20

    if is_catch_all and base > 45:
        base = 45

    if mx_provider == "google":
        base -= 5
    elif mx_provider == "microsoft":
        base += 10

    if email_source.startswith("pattern_"):
        base -= 10
    elif email_source == "scraped":
        base += 10

    return max(0, min(100, base))


# ── 8. verify_single ─────────────────────────────────────────────────────────

def verify_single(row: dict, mx_cache: dict, catchall_cache: dict,
                  skip_catchall_smtp: bool = False) -> dict:
    try:
        email_val = None
        email_col = None
        for col in EMAIL_COLS:
            val = row.get(col, "").strip()
            if val:
                email_val = val
                email_col = col
                break

        email_verified = ""
        email_confidence = 0
        email_source = "unknown"
        email_status_detail = ""
        mx_provider = "none"
        is_catch_all_val = "unknown"
        smtp_code = 0

        if email_val and validate_format(email_val):
            email_source = "scraped"
            domain = email_val.split("@")[1]
            mx_hosts = get_mx_records(domain, mx_cache)
            if not mx_hosts:
                email_verified = "no_mx"
                email_confidence = 5
                email_status_detail = "Domain has no MX records"
            else:
                mx_provider = detect_mx_provider(mx_hosts)
                catch_all = None
                if domain in catchall_cache:
                    catch_all = catchall_cache[domain]
                elif not skip_catchall_smtp:
                    catch_all = is_catch_all(domain, mx_hosts)
                    catchall_cache[domain] = catch_all

                is_catch_all_val = str(catch_all).lower() if catch_all is not None else "unknown"
                smtp_code, smtp_msg = smtp_verify(email_val, mx_hosts)

                # Google special handling
                if smtp_code in (421, 0) and mx_provider == "google":
                    email_verified = "unverifiable"
                    email_confidence = 55
                    email_status_detail = "Google blocks SMTP probes — address likely valid if pattern match"
                elif smtp_code in (250, 251) and not catch_all:
                    email_verified = "true"
                    email_confidence = compute_confidence(smtp_code, False, mx_provider, email_source)
                    email_status_detail = "Mailbox confirmed via SMTP (code 250)"
                elif smtp_code in (250, 251) and catch_all:
                    email_verified = "catch_all"
                    email_confidence = compute_confidence(smtp_code, True, mx_provider, email_source)
                    email_status_detail = "Domain accepts all mail — cannot confirm individual mailbox"
                elif smtp_code in (550, 551, 552, 553):
                    email_verified = "false"
                    email_confidence = 0
                    email_status_detail = f"Mailbox rejected by server (code {smtp_code})"
                else:
                    email_verified = "unverifiable"
                    email_confidence = compute_confidence(smtp_code, catch_all or False, mx_provider, email_source)
                    email_status_detail = f"Server unreachable or greylisted (code {smtp_code})"

        elif not email_val or not email_val.strip():
            # Generate patterns and try
            patterns = generate_email_patterns(row)
            best_result = None
            for pattern_email, source_label in patterns:
                if not validate_format(pattern_email):
                    continue
                domain = pattern_email.split("@")[1]
                mx_hosts = get_mx_records(domain, mx_cache)
                if not mx_hosts:
                    if best_result is None:
                        best_result = (pattern_email, source_label, "no_mx", 5, "Domain has no MX records", "none", "unknown", 0)
                    continue
                mx_provider = detect_mx_provider(mx_hosts)
                catch_all = None
                if domain in catchall_cache:
                    catch_all = catchall_cache[domain]
                elif not skip_catchall_smtp:
                    catch_all = is_catch_all(domain, mx_hosts)
                    catchall_cache[domain] = catch_all

                code, msg = smtp_verify(pattern_email, mx_hosts)
                is_ca = str(catch_all).lower() if catch_all is not None else "unknown"

                if code in (250, 251):
                    email_verified = "catch_all" if catch_all else "true"
                    email_confidence = compute_confidence(code, catch_all or False, mx_provider, source_label)
                    email_status_detail = "Mailbox confirmed via SMTP (code 250)"
                    email_source = source_label
                    mx_provider = mx_provider
                    is_catch_all_val = is_ca
                    smtp_code = code
                    break
                elif code in (550, 551, 552, 553):
                    continue
                else:
                    if best_result is None:
                        best_result = (pattern_email, source_label,
                                       "unverifiable",
                                       compute_confidence(code, catch_all or False, mx_provider, source_label),
                                       f"Server response code {code}",
                                       mx_provider, is_ca, code)

            if not email_verified and best_result:
                email_val = best_result[0]
                email_source = best_result[1]
                email_verified = best_result[2]
                email_confidence = best_result[3]
                email_status_detail = best_result[4]
                mx_provider = best_result[5]
                is_catch_all_val = best_result[6]
                smtp_code = best_result[7]

            if not email_verified and not email_val:
                email_verified = "no_mx"
                email_confidence = 0
                email_status_detail = "No email found and no valid patterns"
        else:
            email_verified = "invalid_format"
            email_confidence = 0
            email_status_detail = "Email address format is invalid"

        row["email_verified"] = email_verified
        row["email_confidence"] = email_confidence
        row["email_source"] = email_source
        row["email_status_detail"] = email_status_detail
        row["mx_provider"] = mx_provider
        row["is_catch_all"] = is_catch_all_val

        # Port 25 block detection
        with port25_lock:
            if port25_attempts >= 3 and port25_failures == port25_attempts:
                logger.warning("⚠️  WARNING: Port 25 may be blocked on this machine. "
                               "SMTP verification will be limited. "
                               "Consider running on a VPS with port 25 open.")

    except Exception as e:
        logger.error(f"Error verifying row: {e}")
        row["email_verified"] = "unverifiable"
        row["email_confidence"] = 0
        row["email_source"] = "unknown"
        row["email_status_detail"] = f"Script error: {str(e)[:100]}"
        row["mx_provider"] = "none"
        row["is_catch_all"] = "unknown"

    return row


# ── 9. main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SG Email Verifier — zero-cost")
    parser.add_argument("input", nargs="?", default="leads/sg_leads_raw.csv")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument("--workers", type=int, default=5, help="Concurrent SMTP workers (default: 5, max: 10)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests per domain (seconds)")
    parser.add_argument("--skip-catchall-smtp", action="store_true", help="Skip SMTP probe for catch-all domains")
    args = parser.parse_args()

    workers = min(args.workers, 10)

    input_path = args.input
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_verified{ext}"

    # Read CSV
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    logger.info(f"Loaded {len(rows)} rows from {input_path}")

    mx_cache = {}
    catchall_cache = {}

    # Per-domain rate limiting
    domain_last_request = {}
    domain_locks = defaultdict(threading.Lock)
    rate_lock = threading.Lock()

    def rate_limited_verify(row):
        domain = None
        for col in EMAIL_COLS:
            val = row.get(col, "").strip()
            if val:
                domain = val.split("@")[1] if "@" in val else None
                break
        if not domain:
            for col in DOMAIN_COLS:
                val = row.get(col, "").strip()
                if val:
                    domain = re.sub(r'^https?://', '', val).split("/")[0]
                    break
        if domain:
            lock = domain_locks[domain]
            with lock:
                now = time.time()
                last = domain_last_request.get(domain, 0)
                diff = now - last
                if diff < args.delay:
                    time.sleep(args.delay - diff)
                domain_last_request[domain] = time.time()
        return verify_single(row, mx_cache, catchall_cache, args.skip_catchall_smtp)

    results = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(rate_limited_verify, row): i for i, row in enumerate(rows)}
            for future in tqdm(as_completed(futures), total=len(rows), desc="Verifying emails"):
                try:
                    result = future.result()
                    results.append((futures[future], result))
                except Exception as e:
                    logger.error(f"Future error: {e}")

        results.sort(key=lambda x: x[0])
        results = [r for _, r in results]

    except KeyboardInterrupt:
        logger.info("Interrupted — saving partial results...")
        # Save whatever we have so far
        if results:
            _write_csv(output_path, [r for _, r in sorted(results, key=lambda x: x[0])], rows[0].keys() if rows else [])
        sys.exit(1)

    # Write output
    fieldnames = list(rows[0].keys()) if rows else []
    new_cols = ["email_verified", "email_confidence", "email_source",
                "email_status_detail", "mx_provider", "is_catch_all"]
    for col in new_cols:
        if col not in fieldnames:
            fieldnames.append(col)

    _write_csv(output_path, results, fieldnames)

    # Summary
    counts = {"true": 0, "catch_all": 0, "false": 0, "unverifiable": 0, "no_mx": 0, "invalid_format": 0}
    for r in results:
        v = r.get("email_verified", "")
        if v in counts:
            counts[v] += 1

    safe = counts["true"] + sum(1 for r in results
                                 if r.get("email_verified") == "unverifiable"
                                 and int(r.get("email_confidence", 0)) > 60)

    print(f"\n{Fore.GREEN}✅ Verified (true): {counts['true']}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}🟡 Catch-all: {counts['catch_all']}{Style.RESET_ALL}")
    print(f"{Fore.RED}❌ Invalid/Rejected: {counts['false']}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}⚠️  Unverifiable/Timeout: {counts['unverifiable']}{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLACK_EX}🚫 No MX: {counts['no_mx']}{Style.RESET_ALL}")
    print(f"Total processed: {len(results)}")
    print(f"Estimated safe-to-send: {safe}")
    logger.info(f"Results written to {output_path}")


def _write_csv(path, rows, fieldnames):
    if not rows or not fieldnames:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    main()
