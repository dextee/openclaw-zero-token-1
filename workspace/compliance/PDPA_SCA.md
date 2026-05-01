# PDPA & SCA Compliance Guide — Mirae Advisory Outreach

> **Scope:** Singapore B2B cold email outreach via OpenClaw zero-token stack  
> **Last updated:** 2026-04-22  
> **Penalty:** SGD 1,000,000 or 10% of annual Singapore turnover (whichever is higher) since 1 Oct 2022  
> **Applicable law:** PDPA 2012 (as amended 2020/2022), Spam Control Act 2007

---

## 1. PDPA — Personal Data Protection Act

### 1.1 What PDPA requires for B2B outreach

| Requirement | How we comply | Evidence |
|-------------|---------------|----------|
| **Consent** | Business contact data (work emails) is generally exempt from consent requirements under PDPA **Section 4(1)(b)** — data used for business contact purposes. We ONLY target corporate email addresses (e.g., `name@company.com`), never personal Gmail/Hotmail. | Email pattern validation rejects consumer domains |
| **Purpose Limitation** | Data used ONLY for B2B financing advisory outreach. No resale, no unrelated marketing. | `outreach_history.json` records campaign name + subject |
| **Notification** | Every email includes: company name, physical address, DPO email, unsubscribe mechanism. | `COMPLIANCE.json` → footer appended by both senders |
| **Access / Correction** | DPO email (`dpo@miraeadvisory.com`) handles access/correction requests. | Listed in every email footer |
| **Protection** | Suppression list (`outreach_history.json`) prevents re-contact after opt-out. | `is_suppressed()` check before every send |
| **Retention Limitation** | Lead data retained only while commercially relevant. Suppression list retained indefinitely (legal requirement). | `.outreach_history.json` is permanent; lead CSVs purged after 24 months |
| **Transfer Limitation** | Data does not leave Singapore infrastructure (VPS in SG). No third-party CRM sync without DPO sign-off. | Self-hosted stack on local VPS |
| **DPO Appointment** | Designated DPO with contact email in every email. | `dpo_email` in `COMPLIANCE.json` |
| **Do-Not-Call Register** | N/A — we use email, not telephone marketing. | — |

### 1.2 PDPA penalty trigger checklist

- [ ] **NO consumer email domains** (gmail.com, yahoo.com, hotmail.com, outlook.com) — BLOCKED at leadgen stage
- [ ] **NO personal mobile numbers** used for SMS/telemarketing
- [ ] **Every email has footer** with company name, address, DPO email, unsubscribe link
- [ ] **Unsubscribe honored within 10 business days** (SCA requirement, see §2)
- [ ] **Suppression list checked before every send** — `oh.is_suppressed()`
- [ ] **No re-contact after unsubscribe/bounce** — permanent suppression in `.outreach_history.json`
- [ ] **Data breach response plan:** Notify PDPC within 3 days if breach >500 individuals

---

## 2. SCA — Spam Control Act 2007

### 2.1 SCA requirements for commercial electronic messages

| Requirement | How we comply | Implementation |
|-------------|---------------|----------------|
| **Header accuracy** | `From:` name and email are truthful. `Reply-To` matches sender. | `create_message()` sets `From: "{sender_name} <{email}>"` |
| **Subject line not misleading** | Subject describes actual content. No "RE:" or "FWD:" fakery. | Template subjects are reviewed; no deception |
| **Unsubscribe mechanism** | Every email contains `mailto:` unsubscribe link with pre-filled subject. | Footer: `mailto:dpo@miraeadvisory.com?subject=Unsubscribe%20from%20Mirae%20Advisory` |
| **Unsubscribe validity** | Unsubscribe address must remain valid for **30 days** after sending. | `dpo@miraeadvisory.com` is a permanent mailbox |
| **Honor unsubscribe** | Must stop sending within **10 business days** of receiving unsubscribe request. | `outreach_tracker.py` and `workspace_imap_tracker.py` auto-detect "unsubscribe/stop/remove me" → permanent suppression |
| **Sender identity** | Clear identification of who sent the message and how to contact them. | Footer includes company name, physical address, DPO email |

### 2.2 SCA exemptions that do NOT apply to us

- **Existing relationship exemption:** We are sending cold emails to prospects with NO prior relationship. We do NOT rely on this exemption.
- **Same group exemption:** N/A — not intra-group communication.

We rely on the **business electronic message** provisions and strict operational compliance, not exemptions.

---

## 3. Operational Compliance Procedures

### 3.1 Pre-send compliance gate

Both senders (`gmail_sender.py`, `workspace_smtp_sender.py`) enforce this gate:

1. **Load** `/root/.openclaw/workspace/compliance/COMPLIANCE.json`
2. **Validate** required fields: `company_name`, `physical_address`, `dpo_email`
3. **If any empty** → `COMPLIANCE BLOCK` error. Send is ABORTED.
4. **Check suppression** → `oh.is_suppressed(email)`
5. **If suppressed** → skip with reason logged.
6. **Append footer** → SG-compliant footer added to every body.
7. **Send** → only after all gates pass.

### 3.2 Unsubscribe workflow

```
Recipient clicks mailto: in footer
  ↓
Email arrives at dpo@miraeadvisory.com with subject "Unsubscribe from Mirae Advisory"
  ↓
IMAP tracker (workspace_imap_tracker.py) scans inbox daily
  ↓
Detects "unsubscribe" keyword → calls oh.suppress_email(email)
  ↓
Permanent suppression recorded in .outreach_history.json
  ↓
Future sends to this email are BLOCKED with reason "unsubscribed"
```

**Manual DPO workflow (if tracker fails):**
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --unsubscribe user@company.com
```

### 3.3 Bounce handling

| Bounce type | Action |
|-------------|--------|
| Hard bounce (invalid recipient) | Permanent suppression — `status: bounced` |
| Soft bounce (mailbox full) | Record as `failed`, retry next campaign |
| Spam folder / blocked | Review deliverability report, adjust copy |

Both trackers (`outreach_tracker.py`, `workspace_imap_tracker.py`) detect bounces automatically.

### 3.4 Data retention schedule

| Data type | Retention | Action after expiry |
|-----------|-----------|---------------------|
| Lead CSVs (raw/enriched) | 24 months | Securely delete |
| Outreach history / suppression | Indefinite | Required by law |
| Email sequences / templates | Indefinite | Business records |
| Campaign performance reports | 24 months | Archive then delete |
| ACRA cache | 30 days | Auto-expired by lookup function |
| MAS cache | 30 days | Auto-expired by lookup function |

---

## 4. Compliance Verification Checklist (before EVERY campaign)

- [ ] `COMPLIANCE.json` has valid `company_name`, `physical_address`, `dpo_email`
- [ ] `dpo_email` mailbox is accessible and monitored
- [ ] Suppression list `.outreach_history.json` is intact
- [ ] All leads have corporate email domains (no gmail/yahoo/hotmail)
- [ ] Email template footer is present in preview
- [ ] Dry-run completed without compliance errors
- [ ] Unsubscribe mailto link is clickable and pre-fills subject correctly
- [ ] Daily send limit ≤450 (Gmail/Workspace safe threshold)
- [ ] Domain throttle active (45s gap between same-domain sends)

---

## 5. Incident Response

### 5.1 If a recipient complains to PDPC

1. **Immediately stop** all sends to the complainant's domain.
2. **Pull records** from `.outreach_history.json` — timestamp, subject, campaign.
3. **Verify** the email had a valid unsubscribe mechanism.
4. **Document** that the address was a corporate email (business contact exemption).
5. **Respond** to PDPC within 21 days with evidence of compliance.

### 5.2 If a data breach occurs

1. **Contain** — stop all outbound sends immediately.
2. **Assess** — how many records, what data, how exposed.
3. **Notify PDPC** within 3 days if >500 individuals affected.
4. **Notify affected individuals** if breach is likely to cause harm.
5. **Remediate** — patch vulnerability, rotate credentials, review access logs.

---

## 6. Technical Controls Summary

| Control | File | Function |
|---------|------|----------|
| Compliance config | `COMPLIANCE.json` | Stores company name, address, DPO email |
| Compliance validator | `gmail_sender.py`, `workspace_smtp_sender.py` | `validate_compliance()` — blocks send if missing |
| Footer builder | `gmail_sender.py`, `workspace_smtp_sender.py` | `build_footer()` — appends PDPA/SCA footer |
| Suppression check | `outreach_history.py` | `is_suppressed()` — checks before every send |
| Auto-suppress | `outreach_tracker.py`, `workspace_imap_tracker.py` | Detects "unsubscribe/stop" → permanent suppression |
| Bounce detection | `outreach_tracker.py`, `workspace_imap_tracker.py` | Parses DSN → hard/soft bounce classification |
| Domain throttle | `domain_throttle.py` | Prevents spam-filter triggering (45s gap) |
| Daily limit | `workspace_smtp_sender.py`, `gmail_sender.py` | Hard cap 450/day |
| Lead quality | `run_full_pipeline.py` | Rejects consumer domains at source |

---

## 7. Glossary

| Term | Meaning |
|------|---------|
| PDPA | Personal Data Protection Act 2012 (Singapore) |
| SCA | Spam Control Act 2007 (Singapore) |
| PDPC | Personal Data Protection Commission |
| DPO | Data Protection Officer |
| DSN | Delivery Status Notification (bounce email) |
| B2B | Business-to-business |
| ICP | Ideal Customer Profile |

---

*This document is a living reference. Update it whenever the legal framework or technical controls change.*
