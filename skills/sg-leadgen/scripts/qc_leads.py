#!/usr/bin/env python3
"""
qc_leads.py — LLM-based final QC pass on lead CSVs.

Sends batches of (company_name, website) pairs to DeepSeek v4 via OpenClaw gateway,
asks it to flag junk entries (page titles, SEO descriptors, non-SG companies, logins),
and writes a QC'd CSV with only KEEP rows.

Usage:
    python3 qc_leads.py input.csv -o output.csv
    python3 qc_leads.py input.csv -o output.csv --batch-size 40 --model deepseek-web/deepseek-v4

Output:
    - output.csv: filtered leads
    - stdout: pipe-separated code block of all kept leads (for bot display)
"""
import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

OPENCLAW_CLI = "/root/openclaw-zero-token/openclaw.mjs"
DEFAULT_MODEL = "deepseek-web/deepseek-v4"
DEFAULT_AGENT = "main"
DEFAULT_TIMEOUT = 180  # seconds per batch


QC_PROMPT_DM_TEMPLATE = """You are a Singapore B2B DM (decision-maker) QC filter. I give you {n} rows: (company_name | website | DM_name | DM_title).

Your job: for each row, decide KEEP or JUNK based on whether the DM looks like a plausible **Singapore-based** decision maker at this specific company.

Mark JUNK if ANY of:
- DM is clearly a **global HQ / founder** when company is a local SG branch. Example: "Howard Schultz - Starbucks founder and architect" for "Starbucks Singapore" → JUNK (Schultz is in Seattle, not SG staff).
- DM's title says they work at a **different company** than the target. Example: target "Shiok Kitchen Catering" but DM title "Lai Fong - National University of Singapore" → JUNK (NUS staff, not Shiok Kitchen).
- DM title reads like **post content, blog snippet or testimonial**, not a real role. Example: "Thanks for coordinating. Only heard praises from..." → JUNK.
- DM name is **generic** ("Jane Doe", "John Smith", "Firstname Lastname", "Admin User").
- DM title is **vague and role-only** with no company mention AND no seniority indicator. Example: "Senior Cook" alone at a company you've never heard of → borderline KEEP; but "Staff Writer at Straits Times" for a construction firm → JUNK.
- DM is historical/former: "ex-CEO", "former director", "retired partner" → JUNK.

Mark KEEP if DM is plausibly a current SG-based DM:
- Title mentions the target company or a clearly-SG entity: "CEO at [Company Name] Pte Ltd", "Director at [Company]" → KEEP.
- Title has SG-specific seniority: "Country Manager, Singapore", "Regional Director APAC".
- Short, plausible role at a small company where the name is the only identifier.

Reply with ONLY a JSON array. Include square brackets. Format exactly:

[{{"i":1,"d":"KEEP"}},{{"i":2,"d":"JUNK","r":"global HQ founder"}},{{"i":3,"d":"KEEP"}}]

Rows:
{rows}

Respond now with ONLY the JSON array starting with [ and ending with ]."""


QC_PROMPT_TEMPLATE = """You are a Singapore B2B lead QC filter. I give you {n} rows (company_name | website). Your job: decide KEEP or JUNK based on whether the company_name string looks like a genuine SG business name AND whether the company_name matches the domain.

Do NOT visit websites. Judge from the text alone.

Mark JUNK if ANY of:
- Name is a page/nav title: "Contact Us", "About", "Contact Page", "Home", "Student Log In", "Course Login", "404", "Page Not Found", "Front Page"
- Name is a process/service heading: "Audit Process", "Our Services", "Tax Advisory Services Fees", "Accounting Services"
- Name is a marketing tagline: "Empowering Businesses", "Make Your Dream Become Reality", "Reliable & Leading Singapore Digital Marketing", "Trusted X Experts"
- Name is a long descriptive SEO phrase (>5 words, generic): "Accounting Services for Business in Jurong East"
- Name is URL-as-name: starts with "www.", "http://", or is literally a domain
- Name is a listicle/tender/article title: "Top 10 ...", "Best X in Singapore", "procurement of ...", "Discover Singapore's Best ..."
- Name is a pure generic descriptor with no brand: "Construction & Renovation Service", "Interior Design Company"
- Name contains suspicious trailing words: "Email Format", "Phone Number", "Company Profile" (data-broker/scraper page)
- **NAME-DOMAIN MISMATCH**: core brand token in company_name is completely absent from the domain root. Example: "Singapore Engineering & Construction Pte Ltd" at `bbr.com.sg` → JUNK (page title, not company). Counter-example: "BBR Construction" at `bbr.com.sg` → KEEP (brand token "BBR" matches).
- Non-SG entities (tophat.com, ama.org, crypto.com, global SaaS)

Mark KEEP if name reads like a real company AND the domain is plausibly consistent:
- Contains a unique brand token: "Kreston", "Paul Wan", "Prism", "Kaizen", "Falkcon", "BBR", "RSM"
- Has a corp suffix: "Pte Ltd", "Pte. Ltd", "PAC", "Holdings", "LLP", "& Co"
- Short 1-2 word SG brand with .sg/.com.sg/.com domain

Examples:
- "Paul Wan & Co" | pwco.com.sg → KEEP (pwco matches Paul Wan & Co)
- "Kreston Helmi Talib" | krestonhelmitalib.com.sg → KEEP
- "Empowering Businesses" | precursor.com.sg → JUNK (tagline, doesn't match "precursor")
- "Singapore Engineering & Construction Pte Ltd" | bbr.com.sg → JUNK (name-domain mismatch — page title)
- "Straits Construction Singapore Pte Ltd Email Format" | straitsconstruction.com → JUNK (data-broker page)
- "Audit Process" | avanta.com.sg → JUNK (page title)
- "Digital Squad" | digitalsquad.com.sg → KEEP

Reply with ONLY a JSON array (NO prose, NO markdown, NO think tags). Include the square brackets. Format exactly:

[{{"i":1,"d":"KEEP"}},{{"i":2,"d":"JUNK","r":"tagline"}},{{"i":3,"d":"KEEP"}}]

Rows:
{rows}

Respond now with ONLY the JSON array starting with [ and ending with ]."""


def build_rows_block(batch):
    lines = []
    for i, row in enumerate(batch, 1):
        name = (row.get("company_name") or "").replace('"', "'")
        site = (row.get("website") or "").strip()
        lines.append(f'{i}. "{name}" | {site}')
    return "\n".join(lines)


def build_rows_block_dm(batch):
    """Build rows for DM QC mode. Only includes rows that actually have a DM."""
    lines = []
    for i, row in enumerate(batch, 1):
        dm_name = (row.get("decision_maker_name") or row.get("contact_1_name") or "").strip()
        if not dm_name:
            continue  # skip rows without a DM (nothing to QC)
        dm_title = (row.get("decision_maker_title") or row.get("contact_1_title") or "").strip()
        name = (row.get("company_name") or "").replace('"', "'")
        site = (row.get("website") or "").strip()
        dm_name_esc = dm_name.replace('"', "'")
        dm_title_esc = dm_title.replace('"', "'")[:120]  # truncate long titles
        lines.append(f'{i}. "{name}" | {site} | DM: "{dm_name_esc}" | Title: "{dm_title_esc}"')
    return "\n".join(lines)


def parse_verdicts(text, batch_size):
    """Extract verdicts from the model response. Returns dict: {index: (decision, reason)}.

    Tolerates responses missing outer [..] brackets, partial JSON, and markdown fences.
    Falls back to regex extraction of per-object verdicts if JSON parsing fails.
    """
    # Strip common wrappers (markdown fences, think tags, etc.)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    text = text.replace("```", "")

    out = {}

    # Try 1: proper JSON array
    m = re.search(r"\[\s*\{.*\}\s*\]", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            for entry in data:
                if isinstance(entry, dict):
                    idx = entry.get("i")
                    dec = (entry.get("d") or "").upper().strip()
                    reason = entry.get("r", "")
                    if isinstance(idx, int) and dec in ("KEEP", "JUNK"):
                        out[idx] = (dec, reason)
            if out:
                return out
        except json.JSONDecodeError:
            pass

    # Try 2: Extract each {"i":N,"d":"..."...} object individually
    obj_pat = re.compile(r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"d"\s*:\s*"(KEEP|JUNK)"(?:\s*,\s*"r"\s*:\s*"([^"]*)")?\s*\}', re.I)
    for mm in obj_pat.finditer(text):
        idx = int(mm.group(1))
        dec = mm.group(2).upper()
        reason = mm.group(3) or ""
        out[idx] = (dec, reason)

    return out


def call_deepseek(prompt, model, agent, timeout_s):
    """Invoke OpenClaw agent CLI with the prompt. Returns the model text response.

    CRITICAL: Uses a unique session-id per call to avoid blocking the main agent
    lane (which serves the Telegram bot). Without this, a DM QC call during a
    campaign would queue behind itself and stall bot responses for minutes.
    """
    import uuid
    sess_id = f"qc-{uuid.uuid4().hex[:12]}"
    cmd = [
        "node", OPENCLAW_CLI, "agent",
        "--agent", agent,
        "--session-id", sess_id,   # isolate from main Telegram bot lane
        "--model", model,
        "--message", prompt,
        "--json",
        "--timeout", str(timeout_s),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s + 30,
            cwd="/root/openclaw-zero-token",
        )
    except subprocess.TimeoutExpired:
        return ""

    if result.returncode != 0:
        # Still try to parse stdout even on non-zero exit
        pass

    # CLI prints JSON on stdout — parse it
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout

    payloads = data.get("result", {}).get("payloads", [])
    if not payloads:
        return ""
    return payloads[0].get("text", "")


def qc_batch(batch, model, agent, timeout_s, mode="company"):
    """QC one batch of rows. Returns list of (row, decision, reason).

    mode='company' (default): evaluates company_name + website; JUNK drops the row.
    mode='dm': evaluates decision_maker + title; JUNK clears DM fields but keeps the row.
    """
    if mode == "dm":
        rows_block = build_rows_block_dm(batch)
        if not rows_block.strip():
            # No DMs to QC — pass everything through unchanged
            return [(row, "KEEP", "no_dm") for row in batch]
        prompt = QC_PROMPT_DM_TEMPLATE.format(n=len(batch), rows=rows_block)
    else:
        prompt = QC_PROMPT_TEMPLATE.format(n=len(batch), rows=build_rows_block(batch))
    response = call_deepseek(prompt, model, agent, timeout_s)
    verdicts = parse_verdicts(response, len(batch))

    out = []
    for i, row in enumerate(batch, 1):
        if i in verdicts:
            decision, reason = verdicts[i]
        else:
            # Model didn't return a verdict — default to KEEP (fail-open: don't lose leads on LLM failure)
            decision, reason = "KEEP", "no_verdict"
        out.append((row, decision, reason))
    return out


def format_code_block(rows):
    """Format kept leads as a pipe-separated code block for chat display."""
    if not rows:
        return "```\n(no leads after QC)\n```"
    lines = ["```", "company_name | website | phone | tier | score"]
    for r in rows:
        lines.append(
            f"{r.get('company_name','').strip()[:45]} | "
            f"{(r.get('website') or '').strip()[:45]} | "
            f"{(r.get('phone') or '').strip()[:20]} | "
            f"{r.get('lead_tier','').strip():4s} | "
            f"{r.get('lead_score','').strip()}"
        )
    lines.append("```")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input CSV path")
    parser.add_argument("-o", "--output", required=True, help="Output CSV (QC'd)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--rejected-log", default=None,
                        help="Optional path to write rejected rows (with reasons)")
    parser.add_argument("--no-codeblock", action="store_true",
                        help="Skip printing the final code-block summary")
    parser.add_argument("--mode", choices=["company", "dm"], default="company",
                        help="company: drop junk rows by name+website. "
                             "dm: clear bad DM fields but keep the row.")
    args = parser.parse_args()

    # Read input
    with open(args.input, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        print(f"QC: empty input {args.input}", file=sys.stderr)
        Path(args.output).write_text("")
        return

    print(f"QC: {len(rows)} rows → DeepSeek v4 in batches of {args.batch_size}", file=sys.stderr)

    # QC in batches
    kept = []
    rejected = []
    _DM_FIELDS = ("decision_maker_name", "decision_maker_title",
                  "contact_1_name", "contact_1_title",
                  "contact_2_name", "contact_2_title",
                  "contact_3_name", "contact_3_title")
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i:i + args.batch_size]
        t0 = time.time()
        verdicts = qc_batch(batch, args.model, args.agent, args.timeout, mode=args.mode)
        elapsed = time.time() - t0

        b_kept = sum(1 for _, d, _ in verdicts if d == "KEEP")
        b_junk = sum(1 for _, d, _ in verdicts if d == "JUNK")
        print(f"QC[{args.mode}]: batch {i // args.batch_size + 1}/{(len(rows) + args.batch_size - 1) // args.batch_size}: "
              f"{b_kept} KEEP, {b_junk} JUNK ({elapsed:.1f}s)", file=sys.stderr)

        for row, decision, reason in verdicts:
            if args.mode == "dm":
                # DM mode: always keep the row; if JUNK, clear DM fields only
                if decision == "JUNK":
                    row_out = dict(row)
                    for k in _DM_FIELDS:
                        if k in row_out:
                            row_out[k] = ""
                    row_out["_dm_qc_cleared"] = reason
                    kept.append(row_out)
                    rejected.append({"company_name": row.get("company_name", ""),
                                     "decision_maker_name": row.get("decision_maker_name", ""),
                                     "decision_maker_title": row.get("decision_maker_title", ""),
                                     "_qc_reason": reason})
                else:
                    kept.append(row)
            else:
                # Company mode: drop JUNK rows
                if decision == "KEEP":
                    kept.append(row)
                else:
                    row_out = dict(row)
                    row_out["_qc_reason"] = reason
                    rejected.append(row_out)

    # Write filtered output
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    # Optional rejected log
    if args.rejected_log and rejected:
        rej_fields = list(fieldnames) + ["_qc_reason"]
        with open(args.rejected_log, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rej_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rejected)

    print(f"QC: kept {len(kept)}/{len(rows)} ({len(rejected)} junk) → {args.output}", file=sys.stderr)

    # Print code-block summary to stdout
    if not args.no_codeblock:
        print(format_code_block(kept))


if __name__ == "__main__":
    main()
