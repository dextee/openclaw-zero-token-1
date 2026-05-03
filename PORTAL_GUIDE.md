# SG Pipeline Portal — Ultimate User Guide

> **URL:** `http://mirae-portal.loca.lt` (or `http://<server-ip>:3030` locally)  
> **Auth:** Basic HTTP auth — username `admin`, password `MiraePortal2026!`

---

## Table of Contents

1. [Getting In](#1-getting-in)
2. [Dashboard](#2-dashboard)
3. [Leads](#3-leads)
4. [Upload](#4-upload)
5. [Outreach & Campaigns](#5-outreach--campaigns)
6. [Sent Email Log](#6-sent-email-log)
7. [Daily Performance Report](#7-daily-performance-report)
8. [IMAP Settings](#8-imap-settings)
9. [Replies](#9-replies)
10. [Deliverability](#10-deliverability)
11. [Master Enrichment](#11-master-enrichment)
12. [Known Issues & Workarounds](#12-known-issues--workarounds)
13. [Tips & Best Practices](#13-tips--best-practices)

---

## 1. Getting In

1. Open the portal URL in your browser.
2. A browser popup asks for username and password:
   - **Username:** `admin`
   - **Password:** `MiraePortal2026!`
3. Click **Logout** in the top-right nav when done. Because this uses Basic Auth, your browser caches the credentials until you fully close the browser or click Logout (which forces a 401 to clear the cache).

---

## 2. Dashboard

The Dashboard is your at-a-glance command center.

| Card                 | What It Shows                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Total Leads**      | All CSV lead files combined (~109K in production)                                                          |
| **Emails Sent**      | Total sent across all campaigns (788 as of May 3)                                                          |
| **Reply Rate**       | Percentage of sent emails that received replies. **Empty until IMAP is configured.**                       |
| **Stages Breakdown** | Bar chart showing lead files by stage: `leadgen`, `enriched`, `verified`, `outreach`, `sequences`, `other` |

**How to use it:**

- Check "Emails Sent" to confirm daily outreach is running.
- If "Reply Rate" is blank, go to **IMAP Settings** and add app passwords.
- Click any stage pill to jump to the Leads page filtered by that stage.

---

## 3. Leads

### 3.1 Leads List (`/portal/leads`)

Shows every lead CSV file in the system. Each card displays:

- **Filename** — click to open the detail table
- **Stage** — `leadgen` → `enriched` → `verified` → `outreach` → `sequences`
- **Row count**
- **Emails with email**
- **Tier breakdown** (A/B/C/D)

**Filters:**

- Click stage pills at the top to show only files in that stage.
- Use the search box to filter by filename.

### 3.2 Lead Detail Table (`/portal/leads/{file_id}`)

Opens a sortable, filterable table of every row in the CSV.

**Controls:**

- **Search** — free-text search across all columns
- **Sendability filter** — `verified` / `risky` / `bad`
- **Tier filter** — A / B / C / D
- **Min score** — numeric minimum lead score
- **Sort** — click any column header to sort ascending/descending
- **Bulk delete** — check rows via checkbox, then click "Delete Selected"
- **Export** — click the filename at the top to download the raw CSV

> ⚠️ **Bulk delete is permanent.** There is no undo. The portal rewrites the CSV in-place.

### 3.3 Inline Edit (API-only)

The backend supports editing any cell in any row, but **there is no UI button for it yet.** If you need to edit a cell, ask the bot in Telegram or use the API directly.

---

## 4. Upload

**What it does:** Upload a new lead CSV to the system.

**Steps:**

1. Go to **Upload** in the nav.
2. Choose a CSV file from your computer.
3. Click **Upload**.
4. The file appears immediately in the **Leads** list with stage `other`.

**CSV requirements:**

- Must be UTF-8 encoded.
- Should have at minimum: `company_name`, `email`, `website`
- The pipeline auto-detects and normalizes columns on import.

---

## 5. Outreach & Campaigns

### 5.1 Outreach Dashboard (`/portal/outreach`)

The main campaign control panel.

**What you see:**

- **Campaign status** — active or paused
- **Sender info** — name, email, company
- **Daily limit** — max emails per day (default 100)
- **Sequences progress** — how many emails sent vs total
- **Runs log** — last 14 run entries (date, sent count, failed count)

**Controls:**
| Button | What It Does |
|--------|--------------|
| **Pause** | Stops the daily cron. No emails send until resumed. |
| **Resume** | Re-enables the daily cron. |
| **Send Now** | Triggers an immediate send (respects daily limit). |
| **Skip Today** | Skips today's scheduled run. Resumes tomorrow. |
| **Retry Today** | Re-runs today's send if it previously failed. |

> 🚨 **Watchdog Banner:** If the campaign has 3+ consecutive failures, a red banner appears. The campaign auto-pauses. Fix the issue (usually SMTP/auth) then click Resume.

### 5.2 Sequence Wizard (`/portal/outreach/wizard`)

Generate new email sequences from a lead file.

**Steps:**

1. Select a **source file** from the dropdown (only `leadgen`/`enriched`/`verified` files appear).
2. Enter your **sender name**.
3. Optionally enter a **campaign name**.
4. Choose **sequence type**:
   - `multi` — standard multi-touch sequence
5. Click **Generate Sequences**.
6. The system creates a new `sequences_*.csv` file and redirects you to the Outreach page.

> ⚠️ The wizard does **not** send emails. It only generates the sequence CSV. Emails are sent by the daily cron at 8am SGT.

---

## 6. Sent Email Log

**New in v2026.05.04**

**URL:** `/portal/sent-log`

Shows every recipient emailed across all campaigns — the customer's exact ask: **"see WHO was emailed."**

**Columns:**

- Company name
- Recipient name + email
- Subject line
- Email number (1 = first touch, 2 = follow-up, etc.)
- Sequence tier (A/B/C)
- Status (`sent`, `pending`, `failed`, `replied`, `bounced`)
- Sent timestamp

**Filters:**

- **Status pills** — click any status to filter (e.g., show only `sent` or `failed`)
- **Search box** — search by company name or email address
- **Pagination** — 100 rows per page

**Use cases:**

- "Did we already email ABC Construction?" → Search the company name.
- "How many emails failed yesterday?" → Filter by `failed` status.
- "Show me all follow-ups (email #2)" → Not yet filterable by email number, but visible in the table.

---

## 7. Daily Performance Report

**New in v2026.05.04**

**URL:** `/portal/reports`

Day-over-day email performance, parsed from `runs.log` and `sequences.csv`.

**Cards (top):**

- Total Sent
- Total Failed
- Total Replied
- Total Bounced

**Table columns:**
| Column | Meaning |
|--------|---------|
| Date | Calendar day |
| Sent | Emails successfully sent |
| Failed | Emails that failed to send |
| Replied | Recipients who replied (requires IMAP) |
| Bounced | Emails that bounced (requires IMAP) |
| Delivery Rate | `sent / (sent + failed)` |
| Reply Rate | `replied / sent` |

**Use cases:**

- Spot deliverability issues (delivery rate dropping)
- Track reply rate trends
- Confirm daily sends are consistent

> ⚠️ **Replied and Bounced columns are 0 until IMAP is configured.** The portal cannot detect replies or bounces without IMAP access.

---

## 8. IMAP Settings

**Critical for:** Reply tracking, bounce detection, follow-up logic.

**URL:** `/portal/imap-settings`

### Adding an IMAP Account

1. Click **Add IMAP Account**.
2. Fill in:
   - **Email address** — the Gmail/Google Workspace address
   - **App Password** — NOT your regular password. Generate this at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - **IMAP Server** — `imap.gmail.com` (default)
   - **IMAP Port** — `993` (default)
3. Click **Save**.
4. Click **Test Connection** to verify.

### Running the Reply Tracker

After adding an account, click **Run Tracker** next to the account. This scans the inbox for replies to sent campaign emails and updates the central reply store.

### Managing Accounts

| Action          | What It Does                        |
| --------------- | ----------------------------------- |
| **Test**        | Verifies IMAP login works           |
| **Run Tracker** | Scans inbox for replies now         |
| **Delete**      | Removes the account from the portal |

> 🔒 **Security:** App passwords are stored in `~/.openclaw/workspace/imap_accounts.json` with `0600` permissions.

---

## 9. Replies

**URL:** `/portal/replies`

Shows all replies detected by the IMAP tracker.

**What you see:**

- Sender name and email
- Reply subject
- Reply body (truncated)
- Detected sentiment: `positive`, `negative`, `neutral`, `unsubscribe`
- Timestamp

**Filter by sentiment:** Use the dropdown to show only positive replies, unsubscribe requests, etc.

> ⚠️ **Empty until IMAP is configured.** No replies appear here until:
>
> 1. IMAP accounts are added in **IMAP Settings**
> 2. The tracker has run at least once

---

## 10. Deliverability

**URL:** `/portal/deliverability`

Monitor email deliverability health.

### Domain Check

1. Enter a domain (e.g., `miraeadvisory.com`).
2. Click **Run Check**.
3. Results appear:
   - **SPF** — PASS / FAIL
   - **DKIM** — PASS / FAIL
   - **DMARC** — PASS / FAIL
   - **MX Records** — present / missing
   - **Health Score** — 0-100

### Why This Matters

| Record    | Purpose                                                    |
| --------- | ---------------------------------------------------------- |
| **SPF**   | Authorizes which servers can send email for your domain    |
| **DKIM**  | Cryptographic signature proving email wasn't tampered with |
| **DMARC** | Tells receivers what to do if SPF/DKIM fail                |

> 🚨 **Enable DKIM in Google Workspace Admin** if DKIM shows FAIL. Without DKIM, emails are much more likely to land in spam.

---

## 11. Master Enrichment

**URL:** `/portal/master`

Bulk enrichment interface for processing lead files through the enrichment pipeline.

**What it does:**

- Select a lead file
- Choose enrichment type (contacts, intent signals, tech stack)
- Run enrichment in real-time via Server-Sent Events (SSE)

> ⚠️ **Master enrichment stream is currently broken.** The backend script `enrich_master_free.py` is missing. Use the Telegram bot (`@miraeclawbot`) to run enrichment instead.

---

## 12. Known Issues & Workarounds

| Issue                                              | Workaround                                                        |
| -------------------------------------------------- | ----------------------------------------------------------------- |
| **Inline edit has no UI**                          | Edit CSV directly or ask the Telegram bot to update a lead        |
| **Master enrichment stream broken**                | Use Telegram bot → `enrich leads`                                 |
| **Reply Rate empty on dashboard**                  | Add IMAP accounts in **IMAP Settings**                            |
| **Replies page empty**                             | Same as above — needs IMAP                                        |
| **Campaigns redirects to Outreach**                | Normal — campaigns and outreach are merged in this UI             |
| **Sequence wizard generate returned error before** | Fixed — form field was renamed from `source_file` to `input_path` |
| **Bulk delete silently failed before**             | Fixed — row hash computation was inconsistent                     |

---

## 13. Tips & Best Practices

### Daily Workflow

1. Check **Dashboard** → Emails Sent to confirm yesterday's run completed.
2. Check **Daily Performance Report** for any spikes in failures or bounces.
3. Check **Replies** (if IMAP is set up) for responses that need follow-up.
4. If replies are low, check **Deliverability** → domain health.

### Before Starting a New Campaign

1. Generate fresh leads via Telegram bot (`@miraeclawbot`).
2. Upload or verify the lead CSV.
3. Go to **Sequence Wizard**, select the file, generate sequences.
4. Review sequences in the **Outreach** page.
5. Ensure the campaign is **Resumed** (not paused).

### When Something Goes Wrong

1. Check the **Runs Log** on the **Outreach** page for error messages.
2. Check **Deliverability** — SPF/DKIM/DMARC failures cause emails to go to spam.
3. Check **IMAP Settings** — test each account's connection.
4. If the watchdog banner appears (3+ failures), pause → fix → resume.

### Security

- Change the portal password regularly.
- Do not share the `admin` account — each team member should use the Telegram bot for their own campaigns.
- App passwords (IMAP) are scoped and revocable — never use your main Google password.

---

_Last updated: 2026-05-04_  
_Portal version: 2026.05.04_
