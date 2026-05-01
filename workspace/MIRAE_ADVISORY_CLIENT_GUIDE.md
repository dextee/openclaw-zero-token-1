# Mirae Advisory — B2B Lead Generation & Outreach System
## Production Guide for Client Review

**Prepared for:** miraeadvisory.com  
**System:** OpenClaw Zero-Token AI Pipeline  
**Date:** April 2026  
**Model:** DeepSeek V4 (primary) / Qwen 3.5+ (fallback)  

---

## 1. Executive Summary

Mirae Advisory operates a **fully automated, zero-API-cost B2B growth pipeline** built on OpenClaw. The system generates Singapore SME leads, enriches them with intent signals and contact data, verifies emails via direct SMTP handshake, and sends personalized cold outreach sequences — all without paying for LinkedIn Sales Navigator, Apollo, Hunter.io, or any lead database subscriptions.

**What you get:**
- **sg-leadgen:** 10–25 qualified Singapore B2B leads per run
- **sg-enrich:** Decision-maker names, direct emails, phones, WhatsApp, tech stack, hiring signals, tender alerts, news mentions
- **sg-verify:** Full DNS + SMTP verification (port 25 open — no paid verification APIs)
- **sg-outreach:** Personalized financing email sequences sent via Google Workspace SMTP

**Total operating cost:** $0 in software/API subscriptions. Only infrastructure (VPS + Google Workspace).

---

## 2. Pipeline Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  sg-leadgen │ ──► │  sg-verify  │ ──► │  sg-enrich  │ ──► │  sg-outreach│
│   (find)    │     │  (validate) │     │  (enrich)   │     │   (send)    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
     │                    │                    │                    │
     ▼                    ▼                    ▼                    ▼
  25 leads           verified             enriched           sequences
  raw CSV            emails               contacts           sent via SMTP
```

**Mandatory pipeline rule:** Verify → Enrich → Verify again. Never enrich unverified emails. Never send outreach on unverified emails.

---

## 3. Step-by-Step: How to Use the Bot

### Step 1 — Generate Leads

**Telegram prompt:**
```
Find 25 construction companies in Singapore
```

**What happens:**
1. Bot runs `sg-leadgen` pipeline
2. Searches 7 query variations + Yellow Pages SG (yelu.sg)
3. Scrapes websites for emails, phones, decision makers
4. Deduplicates and scores leads 0–100
5. Outputs CSV to `/root/.openclaw/workspace/leads/`

**Time:** ~30–60 seconds  
**Output:** `sg_leads_20260422_construction.csv`

---

### Step 2 — Verify Emails (First Pass)

**Telegram prompt:**
```
Verify the emails from the construction leads I just generated
```

**What happens:**
1. Bot reads `sg-verify/SKILL.md`
2. Runs `verify_emails.py` in batches of 5–10
3. DNS MX lookup + SMTP RCPT TO handshake
4. Classifies each email: `true` / `catch_all` / `false` / `unverifiable` / `no_mx`

**Time:** ~1–3 minutes per batch  
**Output:** `sg_leads_20260422_construction_verified.csv`

**Key statuses:**
| Status | Meaning | Action |
|--------|---------|--------|
| `true` | SMTP accepted, not catch-all | ✅ Safe to contact |
| `catch_all` | Domain accepts all mail | ⚠️ Use with caution |
| `false` | SMTP rejected (mailbox doesn't exist) | ❌ Discard |
| `unverifiable` | Google/Microsoft blocks probe | ⚠️ Often valid for Google Workspace |
| `no_mx` | No mail server found | ❌ Discard |

---

### Step 3 — Enrich Leads

**Telegram prompt:**
```
Enrich the verified construction leads
```

**What happens:**
1. Bot reads `sg-enrich/SKILL.md`
2. Runs `enrich_leads.py --skip-google` in batches of 10
3. Detects: tech stack, WhatsApp numbers, personalization hooks
4. Optionally runs `enrich_contacts.py` for decision-maker deep-dive
5. Computes `lead_score_v2` (original score + enrichment bonus)

**Time:** ~40–80 seconds per 10-lead batch  
**Output:** `sg_leads_20260422_construction_enriched.csv`

**New columns added:**
- `tech_stack` — WordPress, Shopify, Salesforce, etc.
- `whatsapp_number` — +65 number if found on website
- `intent_signals` — `gebiz_tender`, `hiring_sales`, `news_funding`
- `personalization_hook` — Icebreaker for email opening
- `lead_score_v2` — Updated score (0–100+)

---

### Step 4 — Verify Again (New Emails)

**Telegram prompt:**
```
Verify the enriched leads again — there may be new emails from contact enrichment
```

**Why:** `enrich_contacts.py` often finds new emails from `/contact` pages that weren't on the homepage. These must be verified before outreach.

**Time:** ~1–3 minutes per batch  
**Output:** `sg_leads_20260422_construction_enriched_verified.csv`

---

### Step 5 — Send Outreach

**Telegram prompt:**
```
Send financing outreach to the verified construction leads
```

**What happens:**
1. Bot asks: **"What sender name should I use?"**
2. You reply: **"Dexter Ng"** (or any name)
3. Bot runs:
   - `generate_sequences.py --sender-name "Dexter Ng"`
   - `validate_sequences.py`
   - `workspace_smtp_sender.py --dry-run` (preview)
   - `workspace_smtp_sender.py` (live send)
4. Emails sent with 2–3 second delays + 45-second domain throttling

**Time:** ~5–10 seconds per email  
**Output:** Sequences CSV + send confirmation

---

## 4. Email Template — Full Text

### Subject Rotation (A/B Test)

The system rotates between **2 subjects** deterministically based on lead ID hash:

1. **"Need Business Financing? We Compare Lenders So You Don't Have To"**
2. **"Tired of Bank Rejections? We Find the Right Financing for You"**

---

### Email #1 — Opening Email

```
Hi {{first_name}},

Mirae Advisory here — we are a Singapore-based SME financing firm led by former bankers. We help businesses like {{company_name}} get the right funding without the run-around.

We offer:
- Working Capital Loan
- Trade Lines
- Invoice Factoring
- Revenue Based Financing
- Property Backed Loan
- Personal Loan

Quick question: is {{company_name}} looking to expand or optimize your funding setup in the next 6 months?

If yes, grab a 15-min slot here and we'll walk you through what you'd likely qualify for — no obligation:
https://calendar.app.google/Vt8th4ByKcCxD4Fv6

{{sender_name}} | Mirae Advisory | miraeadvisory.com
```

**Personalization tokens filled automatically:**
- `{{first_name}}` — From `decision_maker_name` column
- `{{company_name}}` — From `company_name` column
- `{{sender_name}}` — From your reply to the bot

---

### Email #2 — Follow-up (Day 3–4)

```
Hi {{first_name}},

Quick follow-up. An {{industry}} business in {{area}} we recently helped was turned down by 3 banks before we matched them with an alternative lender. Their rate ended up 1.2% lower than what their usual bank offered.

Same business, same financials — just the right lender.

Worth a brief call to see what's available for {{company_name}}?

{{sender_name}} | Mirae Advisory | miraeadvisory.com
```

---

### Email #3 — Breakup / Last Chance (Day 6–8)

```
Hi {{first_name}},

Last note from me. If {{company_name}} ever needs help comparing lenders or exploring financing options, my door's open.

Best of luck to you and the team in {{area}}.

{{sender_name}} | Mirae Advisory | miraeadvisory.com
```

---

### Sequence Scheduling by Tier

| Lead Score | Tier | Emails | Delays |
|------------|------|--------|--------|
| 80+ | A (Aggressive) | 3 | 0, 3, 3 days |
| 45–79 | B (Nurture) | 5 | 0, 4, 4, 4, 4 days |
| 20–44 | C (Slow Burn) | 7 | 0, 5, 5, 5, 5, 5, 5 days |

---

## 5. FAQ

### Q: How many leads can I generate per day?
**A:** The bot caps at **25 leads per run** to stay within DeepSeek's rate limits and gateway timeouts. You can run multiple industries per day.

### Q: Where do the leads come from?
**A:** Five search backends with automatic fallback:
1. SearXNG (self-hosted, preferred)
2. Mojeek (no CAPTCHA)
3. DuckDuckGo
4. Yellow Pages SG (yelu.sg)
5. Startpage (last resort)

### Q: Are the emails actually verified?
**A:** Yes. Every email undergoes **DNS MX lookup + SMTP RCPT TO handshake** on port 25. The VPS has port 25 open, so full verification works. No paid API needed.

### Q: What if the SMTP verification says "catch_all"?
**A:** Catch-all means the domain accepts mail for ANY address (e.g., `anything@company.com.sg`). These are typically safe for legitimate businesses but slightly riskier. We flag them with lower confidence.

### Q: Can I send to leads outside Singapore?
**A:** The pipeline is optimized for Singapore. The search queries include "Singapore" and "Pte Ltd." Non-SG domains are filtered. You'd need to customize the pipeline for other markets.

### Q: What sender email is used?
**A:** `admin@miraeadvisory.com` via Google Workspace SMTP relay. The bot asks you for ONLY the sender name (e.g., "Dexter Ng"). Title defaults to "Business Development" and company to "Mirae Advisory."

### Q: Will I get blacklisted?
**A:** The system has multiple protections:
- **Domain throttling:** 45-second minimum between sends to the same domain
- **Daily limit:** 450 max (default), recommended 100–150/day
- **Global history:** Prevents re-sending to the same email across campaigns
- **Suppression list:** Auto-blocks unsubscribes, bounces, and negative replies
- **Plain text only:** No HTML (better deliverability)

### Q: How do I track replies?
**A:** Run: `Check replies for the construction campaign`  
The bot runs IMAP tracker, classifies replies as Positive / Negative / Out-of-Office / Neutral, and generates a performance report.

### Q: Can I customize the email template?
**A:** Yes — edit `/root/openclaw-zero-token/skills/sg-outreach/references/sequence_templates.py`. Changes take effect immediately (no rebuild needed for Python).

### Q: What happens if a lead replies "unsubscribe"?
**A:** The reply tracker detects it, adds the email to the global suppression list, and permanently blocks future outreach to that address.

### Q: How much does this cost to run?
**A:**
- **Leadgen:** $0 (no paid APIs)
- **Enrichment:** $0 (no paid APIs)
- **Verification:** $0 (direct SMTP, no verification service)
- **Sending:** $0 (Google Workspace SMTP relay, included in Workspace plan)
- **AI model:** $0 (zero-token web models via browser cookies)
- **Total:** VPS hosting (~$20–50/mo) + Google Workspace (~$6–12/user/mo)

---

## 6. DOs and DON'Ts

### ✅ DO
- **Always verify before enriching.** Unverified emails = reputation damage.
- **Always verify AGAIN after enrichment.** Contact pages often reveal new emails.
- **Use batch sizes:** 5–10 leads per verify batch, 10 per enrich batch.
- **Start with a small test.** Send 5–10 emails first, check replies, then scale.
- **Use `--single` for one-off sends.** This generates only Email #1 with no follow-ups.
- **Provide a real sender name.** The bot asks for it. Use your actual name.
- **Check the dry-run preview** before live sends for large campaigns.
- **Run reply tracking weekly.** Bounces and negative replies hurt deliverability if ignored.

### ❌ DON'T
- **Don't send on unverified emails.** If verify shows <30% true, stop and get better leads.
- **Don't exceed 150 emails/day on a new domain.** Gradually warm up (10→50→100→150 over 4+ weeks).
- **Don't reuse the same /tmp/ files.** Always create fresh mini CSVs for one-off sends.
- **Don't ask the bot for template content.** The financing template is built-in. Never let the bot write its own email copy.
- **Don't hardcode sender names.** Always let the bot ask you. Never use fake names.
- **Don't ignore bounces.** Hard bounces auto-suppress, but soft bounces need attention.
- **Don't run leadgen on overly broad terms.** "Business" returns poor results. Use specific industries: "construction," "interior design," "logistics."

---

## 7. Quality Controls & Filters

### Leadgen Filters (What Gets Rejected)
- Government sites (`.gov.sg`)
- Educational institutions (`.edu.sg`)
- Job boards (Indeed, JobStreet, Glassdoor)
- News sites (CNBC, Straits Times)
- Global brands (Shopify, Stripe, KPMG)
- Chinese tutorial sites (Baidu, Zhihu, CSDN)
- Research firms (Gartner, Forrester)
- Social media (LinkedIn, Facebook, Twitter/X)
- App stores
- Loan providers (moneylenders — we want borrowers, not lenders)
- Co-working spaces
- Generic SEO phrases without real company names

### Scoring Model (0–100)
| Signal | Points |
|--------|--------|
| Email present | 25 |
| Phone present | 15 |
| Website exists | 10 |
| Decision maker (name + title) | 15 |
| Recent activity / notes | 5 |

**Tier mapping:**
- Hot (80+): Aggressive 3-email sequence
- Warm (45–79): Nurture 5-email sequence
- Cold (20–44): Slow burn 7-email sequence

---

## 8. Known Limitations (Honest Assessment)

| Area | Limitation | Impact | Mitigation |
|------|-----------|--------|------------|
| **Leadgen depth** | No ACRA integration, no LinkedIn scraping | UEN and LinkedIn URLs rarely populated | Search + website scraping compensates |
| **JS-rendered sites** | Only raw HTML fetched | Single-page apps return minimal content | Affects ~10–20% of modern sites |
| **Enrichment speed** | Google scraping for intent signals | Slow (~2–4 min for 5 leads), fragile to Google UI changes | Use `--skip-google` for faster runs |
| **Contact enrichment** | DM columns may drop if missing from input | `decision_maker_name` not written to output | Ensure input CSV has DM columns |
| **SMTP retry** | Workspace sender has no retry logic | Temporary failures become permanent fails | Port 25 is open; failures are rare |
| **Negative reply suppression** | "negative_reply" status not in suppression list | Negative replies don't block future sends | Manual suppression via CLI if needed |
| **Saleshandy export** | Custom fields empty | `tech_stack`, `personalization_hook` not in sequences CSV | Export from enriched leads instead |
| **Scoring realism** | "Verified email" = presence, not true verification | Scores may be inflated | Use sg-verify for actual verification |

---

## 9. Deliverability Setup Checklist

For best inbox placement, ensure these DNS records are configured for `miraeadvisory.com`:

| Record | Value | Status |
|--------|-------|--------|
| **SPF** | `v=spf1 include:_spf.google.com ~all` | ⚠️ Verify in Google Workspace Admin |
| **DKIM** | Enable in Google Workspace Admin | 🔴 Missing — biggest spam impact |
| **DMARC** | `v=DMARC1; p=quarantine; rua=mailto:dmarc@miraeadvisory.com` | ⚠️ Recommended |

**Current deliverability score:** ~75/100  
**Biggest improvement:** Enabling DKIM in Google Workspace Admin Console.

---

## 10. Support & Troubleshooting

| Issue | Quick Fix |
|-------|-----------|
| "AUTH_FAILED" from sender | Check `.workspace_smtp_config.json` has correct credentials |
| "Skipped (dup)" on all leads | These were already contacted. Use `outreach_history.py --check email@example.com` |
| Bot not using tools | Type `/new` to reset session. Ensure message includes keywords like "send", "verify", "find leads" |
| Emails going to spam | Run `deliverability_check.py`. Enable DKIM in Google Workspace. |
| SearXNG not responding | Check `curl http://localhost:8080`. Restart with `systemctl restart searxng` |
| Port 25 blocked | Verify with `telnet gmail-smtp-in.l.google.com 25`. If blocked, contact VPS provider. |

---

## 11. Command Reference (For Power Users)

```bash
# Lead generation
python3 /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py "construction" --target 25 --output /root/.openclaw/workspace/leads/sg_leads_construction.csv

# Verify emails
python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py /root/.openclaw/workspace/leads/sg_leads_construction.csv --output /root/.openclaw/workspace/leads/sg_leads_construction_verified.csv

# Enrich (intent + tech)
python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py /root/.openclaw/workspace/leads/sg_leads_construction_verified.csv --skip-google --limit 10 --output /root/.openclaw/workspace/leads/sg_leads_construction_enriched.csv

# Enrich (contacts deep-dive)
python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py /root/.openclaw/workspace/leads/sg_leads_construction_enriched.csv --limit 10 --output /root/.openclaw/workspace/leads/sg_leads_construction_contacts.csv

# Generate sequences
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/generate_sequences.py /root/.openclaw/workspace/leads/sg_leads_construction_enriched.csv --sender-name "Dexter Ng" --output /root/.openclaw/workspace/leads/sg_sequences_construction.csv

# Validate
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/validate_sequences.py --sequences /root/.openclaw/workspace/leads/sg_sequences_construction.csv

# Send (dry run first)
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py --sequences /root/.openclaw/workspace/leads/sg_sequences_construction.csv --dry-run

# Send (live)
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py --sequences /root/.openclaw/workspace/leads/sg_sequences_construction.csv

# Track replies
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py --sequences /root/.openclaw/workspace/leads/sg_sequences_construction.csv --report

# History stats
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --stats
```

---

*This guide reflects the system state as of April 2026. The pipeline is actively maintained and improved. For questions, contact the system administrator.*
