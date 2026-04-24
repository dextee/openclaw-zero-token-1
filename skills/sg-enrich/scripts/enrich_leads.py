#!/usr/bin/env python3
"""SG Lead Enrichment Pipeline — Zero-Cost.

Discovers intent signals, tech stack, and WhatsApp numbers using
only browser-based scraping and free public data sources.

Usage:
    python3 enrich_leads.py leads/sg_leads_verified.csv
    python3 enrich_leads.py leads/sg_leads_verified.csv --skip-google
    python3 enrich_leads.py leads/sg_leads_verified.csv --workers 3 --min-score 40
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import urllib3
from colorama import Fore, Style, init as colorama_init
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
colorama_init(autoreset=True)

from tech_stack import detect_tech_stack
from whatsapp_finder import find_whatsapp
from intent_signals import get_intent_signals

logger = logging.getLogger("sg-enrich")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
fmt = logging.Formatter("[%(asctime)s] %(levelname)s — %(message)s")
console_handler.setFormatter(fmt)
logger.addHandler(console_handler)

ICP_TECH = {"Shopify", "WooCommerce", "HubSpot", "Salesforce", "Magento", "WordPress"}


# ── Personalization Hook ─────────────────────────────────────────────────────

def derive_pain_point(job_title: str) -> str:
    jt = job_title.lower()
    if "sales" in jt or "business" in jt:
        return "outbound growth intent"
    if "it" in jt or "software" in jt or "developer" in jt:
        return "tech investment cycle"
    if "marketing" in jt:
        return "demand generation focus"
    if "operations" in jt or "logistics" in jt:
        return "operational scaling"
    if "finance" in jt:
        return "financial management priority"
    return "team expansion"


def generate_personalization_hook(row: dict) -> str:
    tender = row.get("recent_tender", "")
    tender_val = row.get("tender_value", "")
    news = row.get("news_signal", "")
    hiring = row.get("hiring_signals", "")
    tech = row.get("tech_stack", "")
    wa = row.get("whatsapp_number", "")
    industry = row.get("industry", "B2B")
    area = row.get("area", "Singapore")

    if tender == "True" and tender_val:
        return f"Recently active on GeBIZ with {tender_val} in contracts — scaling operations signal"
    if news:
        return f"Noticed: {news[:80]}"
    if hiring:
        titles = hiring.split(",")
        if titles:
            return f"Currently hiring {titles[0]} — signals {derive_pain_point(titles[0])}"
    if tech:
        tech_list = tech.split(",")
        for t in tech_list:
            if t.strip() in ("Shopify", "WooCommerce"):
                return f"Running e-commerce on {t.strip()} — likely focused on digital growth"
            if t.strip() in ("HubSpot", "Salesforce"):
                return f"Already using {t.strip()} — sales stack in place"
    if wa:
        return "WhatsApp-reachable — likely responsive to direct outreach"
    return f"Active {industry} business in {area}"


def determine_outreach_channel(row: dict) -> str:
    wa = row.get("whatsapp_number", "")
    email_v = row.get("email_verified", "")
    linkedin = row.get("linkedin_url", "")

    if wa and email_v in ("true", "catch_all"):
        return "email+whatsapp"
    if email_v in ("true", "catch_all"):
        return "email"
    if linkedin and email_v not in ("true", "catch_all"):
        return "linkedin"
    return "email"


def compute_enrichment_bonus(row: dict) -> int:
    bonus = 0
    if row.get("recent_tender") == "True":
        bonus += 15
    hiring = row.get("hiring_signals", "")
    if hiring:
        bonus += 20
    if row.get("news_signal", ""):
        bonus += 15
    if row.get("whatsapp_number", ""):
        bonus += 10
    tech = row.get("tech_stack", "")
    if tech:
        bonus += 10
        tech_list = [t.strip() for t in tech.split(",")]
        if any(t in ICP_TECH for t in tech_list):
            bonus += 5
    return min(bonus, 50)


# ── Enrich Single Row ────────────────────────────────────────────────────────

def enrich_website(url: str, phone: str = None) -> dict:
    """Run tech detection + WhatsApp finder for one URL."""
    result = {"tech_stack": "", "whatsapp_number": ""}
    if not url:
        return result
    try:
        tech = detect_tech_stack(url)
        result["tech_stack"] = ",".join(tech) if tech else ""
    except Exception:
        result["tech_stack"] = ""
    try:
        wa_num, wa_source = find_whatsapp(url, phone)
        result["whatsapp_number"] = wa_num if wa_source != "not_found" else ""
    except Exception:
        result["whatsapp_number"] = ""
    return result


def enrich_row(row: dict, skip_google: bool = False) -> dict:
    """Enrich a single lead row."""
    try:
        website = ""
        for col in ("website", "Website", "domain", "Domain"):
            val = row.get(col, "").strip()
            if val:
                website = val
                break

        # Website enrichment (tech stack + WhatsApp)
        if website:
            web_result = enrich_website(website, row.get("phone", ""))
            row["tech_stack"] = web_result.get("tech_stack", "")
            row["whatsapp_number"] = web_result.get("whatsapp_number", "")
        else:
            row["tech_stack"] = ""
            row["whatsapp_number"] = ""

        # Google intent signals
        if not skip_google:
            company = row.get("company_name", row.get("company", "")).strip()
            if company:
                signals = get_intent_signals(company, website, row.get("industry", ""))
                row["recent_tender"] = str(signals["recent_tender"]) if signals["recent_tender"] is not None else "unknown"
                row["tender_value"] = signals.get("tender_value", "")
                row["hiring_signals"] = ",".join(signals["hiring_signals"])
                row["news_signal"] = signals.get("news_signal", "")
                row["intent_signals"] = ",".join(signals["raw_intent_list"])
            else:
                row["recent_tender"] = "unknown"
                row["tender_value"] = ""
                row["hiring_signals"] = ""
                row["news_signal"] = ""
                row["intent_signals"] = ""
        else:
            row["recent_tender"] = "unknown"
            row["tender_value"] = ""
            row["hiring_signals"] = ""
            row["news_signal"] = ""
            row["intent_signals"] = ""

        # Personalization hook
        row["personalization_hook"] = generate_personalization_hook(row)

        # Outreach channel
        row["outreach_channel"] = determine_outreach_channel(row)

        # Enrichment bonus
        bonus = compute_enrichment_bonus(row)
        row["enrichment_score_bonus"] = bonus
        try:
            original_score = int(row.get("lead_score", 0))
        except (ValueError, TypeError):
            original_score = 0
        row["lead_score_v2"] = original_score + bonus

    except Exception as e:
        logger.error(f"Error enriching row: {e}")
        row.setdefault("tech_stack", "")
        row.setdefault("whatsapp_number", "")
        row.setdefault("recent_tender", "unknown")
        row.setdefault("tender_value", "")
        row.setdefault("hiring_signals", "")
        row.setdefault("news_signal", "")
        row.setdefault("intent_signals", "")
        row.setdefault("personalization_hook", "Enrichment error")
        row.setdefault("outreach_channel", "email")
        row.setdefault("enrichment_score_bonus", 0)
        row.setdefault("lead_score_v2", row.get("lead_score", 0))

    return row


# ── Main ─────────────────────────────────────────────────────────────────────

def _write_progress(progress_file: str, data: dict):
    """Atomically write progress JSON so readers never see partial data."""
    if not progress_file:
        return
    tmp = progress_file + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, progress_file)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="SG Lead Enrichment — zero-cost")
    parser.add_argument("input", nargs="?", default="leads/sg_leads_verified.csv")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent workers for website fetching (default: 3, max: 5)")
    parser.add_argument("--skip-google", action="store_true", help="Skip GeBIZ + job + news Google searches")
    parser.add_argument("--min-score", type=int, default=0, help="Only enrich leads with lead_score >= N")
    parser.add_argument("--limit", type=int, default=0, help="Max leads to process (0 = all). CRITICAL: use 10 or less per batch for OpenClaw stability.")
    parser.add_argument("--offset", type=int, default=0, help="Start at row N (0-based). Use with --limit for chunked processing.")
    parser.add_argument("--progress-file", default=None, help="Path to write JSON progress updates (read by bot for heartbeat)")
    args = parser.parse_args()

    workers = min(args.workers, 5)
    input_path = args.input
    progress_file = args.progress_file

    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        _write_progress(progress_file, {"status": "failed", "error": f"Input file not found: {input_path}", "completed": 0, "total": 0})
        sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_enriched{ext}"

    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Filter by min score
    if args.min_score > 0:
        rows = [r for r in rows if int(r.get("lead_score", 0)) >= args.min_score]

    # Apply offset + limit for chunked processing
    if args.offset > 0:
        rows = rows[args.offset:]
    if args.limit > 0:
        rows = rows[:args.limit]

    total = len(rows)
    logger.info(f"Loaded {total} rows from {input_path}")

    # Write initial progress
    start_time = time.time()
    _write_progress(progress_file, {
        "status": "running",
        "completed": 0,
        "total": total,
        "elapsed_s": 0,
        "eta_s": None,
        "last_company": "",
        "output_file": output_path,
    })

    results = []
    completed_count = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(enrich_row, row, args.skip_google): i
                       for i, row in enumerate(rows)}
            for future in tqdm(as_completed(futures), total=total, desc="Enriching"):
                result = future.result()
                results.append((futures[future], result))
                completed_count += 1

                # Write progress every 5 rows
                if completed_count % 5 == 0 or completed_count == total:
                    elapsed = time.time() - start_time
                    rate = completed_count / elapsed if elapsed > 0 else 0
                    eta = (total - completed_count) / rate if rate > 0 else None
                    company = result.get("company_name", result.get("company", ""))
                    _write_progress(progress_file, {
                        "status": "running",
                        "completed": completed_count,
                        "total": total,
                        "percent": round(completed_count / total * 100),
                        "elapsed_s": round(elapsed),
                        "eta_s": round(eta) if eta else None,
                        "last_company": company,
                        "output_file": output_path,
                    })
                    print(f"PROGRESS: {completed_count}/{total} completed ({round(completed_count/total*100)}%) — {company}", flush=True)

        results.sort(key=lambda x: x[0])
        results = [r for _, r in results]

    except KeyboardInterrupt:
        logger.info("Interrupted — saving partial results...")
        elapsed = time.time() - start_time
        _write_progress(progress_file, {"status": "interrupted", "completed": completed_count, "total": total, "elapsed_s": round(elapsed)})
        if results:
            _write_csv(output_path, [r for _, r in sorted(results, key=lambda x: x[0])],
                       list(rows[0].keys()) if rows else [])
        sys.exit(1)

    except Exception as e:
        elapsed = time.time() - start_time
        _write_progress(progress_file, {"status": "failed", "error": str(e), "completed": completed_count, "total": total, "elapsed_s": round(elapsed)})
        logger.error(f"Enrichment failed: {e}")
        sys.exit(1)

    # Write output CSV
    fieldnames = list(rows[0].keys()) if rows else []
    new_cols = ["tech_stack", "whatsapp_number", "recent_tender", "tender_value",
                "hiring_signals", "news_signal", "intent_signals",
                "personalization_hook", "outreach_channel",
                "enrichment_score_bonus", "lead_score_v2"]
    for col in new_cols:
        if col not in fieldnames:
            fieldnames.append(col)

    _write_csv(output_path, results, fieldnames)

    # Summary stats
    elapsed = time.time() - start_time
    wa_count = sum(1 for r in results if r.get("whatsapp_number"))
    tech_count = sum(1 for r in results if r.get("tech_stack"))
    tender_count = sum(1 for r in results if r.get("recent_tender") == "True")
    hiring_count = sum(1 for r in results if r.get("hiring_signals"))
    news_count = sum(1 for r in results if r.get("news_signal"))
    hot_count = sum(1 for r in results if float(r.get("lead_score_v2") or 0) >= 70)
    avg_bonus = sum(int(r.get("enrichment_score_bonus", 0)) for r in results) / max(len(results), 1)

    # Write final success progress
    _write_progress(progress_file, {
        "status": "success",
        "completed": len(results),
        "total": total,
        "elapsed_s": round(elapsed),
        "output_file": output_path,
        "whatsapp": wa_count,
        "tech_stack": tech_count,
        "tenders": tender_count,
        "hiring": hiring_count,
        "news": news_count,
        "hot_leads": hot_count,
    })

    print(f"\nENRICH_SUMMARY: total={len(results)} whatsapp={wa_count} tech={tech_count} tenders={tender_count} hiring={hiring_count} hot={hot_count} elapsed={round(elapsed)}s output={output_path}", flush=True)
    print(f"\n{Fore.CYAN}🔍 Enriched: {len(results)} leads{Style.RESET_ALL}")
    print(f"{Fore.GREEN}📱 WhatsApp found: {wa_count}{Style.RESET_ALL}")
    print(f"{Fore.BLUE}🏗️  Tech stack detected: {tech_count}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}📋 GeBIZ tender activity: {tender_count}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}💼 Hiring signals found: {hiring_count}{Style.RESET_ALL}")
    print(f"{Fore.RED}📰 News signals found: {news_count}{Style.RESET_ALL}")
    print(f"Avg enrichment score bonus: {avg_bonus:.1f} pts")
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
