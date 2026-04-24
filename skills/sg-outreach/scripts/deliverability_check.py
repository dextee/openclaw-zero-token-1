#!/usr/bin/env python3
"""Quick deliverability check for the sending domain.

Checks SPF, DKIM, DMARC, and MX records. Gives actionable fixes.

Usage:
    python3 deliverability_check.py
"""

import json
import os
import subprocess
import sys

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".workspace_smtp_config.json",
)


def _dig(domain: str, rtype: str) -> list:
    try:
        out = subprocess.check_output(
            ["dig", "+short", rtype, domain],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        return [l.strip().strip('"') for l in out.strip().splitlines() if l.strip()]
    except Exception:
        return []


def check_domain(domain: str) -> dict:
    results = {
        "domain": domain,
        "spf": {"records": [], "pass": False, "notes": []},
        "dkim": {"records": [], "pass": False, "notes": []},
        "dmarc": {"records": [], "pass": False, "notes": []},
        "mx": {"records": [], "pass": False, "notes": []},
    }

    # MX
    mx = _dig(domain, "MX")
    results["mx"]["records"] = mx
    if mx:
        results["mx"]["pass"] = True
    else:
        results["mx"]["notes"].append("No MX records found. Email cannot be received.")

    # SPF
    txt = _dig(domain, "TXT")
    spf = [r for r in txt if r.lower().startswith("v=spf1")]
    results["spf"]["records"] = spf
    if spf:
        results["spf"]["pass"] = True
        if "_spf.google.com" not in spf[0].lower() and "include:_spf.google.com" not in spf[0].lower():
            results["spf"]["notes"].append("SPF does not include Google (_spf.google.com). If using Gmail/Workspace, add it.")
        if "~all" in spf[0]:
            results["spf"]["notes"].append("SPF uses ~all (softfail). Consider -all (hardfail) for stronger auth.")
        elif "-all" not in spf[0] and "?all" not in spf[0]:
            results["spf"]["notes"].append("SPF missing explicit all mechanism. Add ~all or -all at the end.")
    else:
        results["spf"]["notes"].append("No SPF record found. Add one immediately.")

    # DKIM — try common selectors
    dkim_selectors = ["google", "default", "selector1", "selector2", "mail"]
    found_selectors = []
    for sel in dkim_selectors:
        recs = _dig(f"{sel}._domainkey.{domain}", "TXT")
        if recs:
            found_selectors.append((sel, recs))
    results["dkim"]["records"] = found_selectors
    if found_selectors:
        results["dkim"]["pass"] = True
    else:
        results["dkim"]["notes"].append(
            "No DKIM record found for common selectors (google, default, selector1, selector2, mail). "
            "Enable DKIM in Google Workspace Admin → Apps → Google Workspace → Gmail → Authenticate email."
        )

    # DMARC
    dmarc = _dig(f"_dmarc.{domain}", "TXT")
    results["dmarc"]["records"] = dmarc
    if dmarc:
        results["dmarc"]["pass"] = True
        rec = dmarc[0].lower()
        if "p=none" in rec:
            results["dmarc"]["notes"].append("DMARC policy is p=none (monitor only). Tighten to p=quarantine once DKIM is working.")
        elif "p=quarantine" in rec:
            results["dmarc"]["notes"].append("DMARC policy is p=quarantine. Good — failed auth emails go to spam, not inbox.")
        elif "p=reject" in rec:
            results["dmarc"]["notes"].append("DMARC policy is p=reject. Strongest protection.")
        if "rua=" not in rec:
            results["dmarc"]["notes"].append("DMARC missing rua= (reporting address). Add one to monitor failures.")
    else:
        results["dmarc"]["notes"].append("No DMARC record found. Add: v=DMARC1; p=quarantine; rua=mailto:admin@YOURDOMAIN.com")

    return results


def print_results(results: dict):
    domain = results["domain"]
    print(f"{Fore.CYAN}Deliverability check for: {domain}{Style.RESET_ALL}\n")

    for check in ("mx", "spf", "dkim", "dmarc"):
        data = results[check]
        status = f"{Fore.GREEN}✓ PASS" if data["pass"] else f"{Fore.RED}✗ FAIL"
        print(f"{status}{Style.RESET_ALL}  {check.upper()}")
        if data["records"]:
            for r in data["records"][:2]:
                print(f"       {r}")
        for note in data["notes"]:
            print(f"       {Fore.YELLOW}→ {note}{Style.RESET_ALL}")
        print()

    # Overall score
    passed = sum(1 for c in ("mx", "spf", "dkim", "dmarc") if results[c]["pass"])
    score = passed * 25
    if score >= 75:
        color = Fore.GREEN
    elif score >= 50:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    print(f"{color}Score: {score}/100 ({passed}/4 checks passing){Style.RESET_ALL}")

    if score < 100:
        print(f"\n{Fore.CYAN}Recommended fix order:{Style.RESET_ALL}")
        print("1. Enable DKIM in Google Workspace Admin (biggest spam impact)")
        print("2. Ensure SPF includes _spf.google.com")
        print("3. Add DMARC record if missing: v=DMARC1; p=quarantine; rua=mailto:admin@" + domain)
        print("4. Tighten DMARC from p=none to p=quarantine once DKIM+SPF are confirmed")


def main():
    domain = None
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        email = config.get("email", "")
        if "@" in email:
            domain = email.split("@")[1]

    if not domain:
        print("Could not detect domain from .workspace_smtp_config.json")
        print("Usage: python3 deliverability_check.py <domain>")
        if len(sys.argv) > 1:
            domain = sys.argv[1]
        else:
            sys.exit(1)

    results = check_domain(domain)
    print_results(results)


if __name__ == "__main__":
    main()
