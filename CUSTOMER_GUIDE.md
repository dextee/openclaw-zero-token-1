# Mirae Advisory Portal — Quick Start Guide

## 🌐 Access the Portal

**URL:** `http://mirae-portal.loca.lt`

When you open the link, your browser will ask for a username and password:

- **Username:** `admin`
- **Password:** _(provided separately by Mirae Advisory)_

Click **Logout** in the top-right when finished.

---

## 📊 Dashboard

This is your homepage. It shows:

- **Total Leads** — how many companies are in the database
- **Emails Sent** — total outreach emails delivered
- **Reply Rate** — % of people who replied _(empty until you add IMAP — see Section 6)_

**Tip:** If "Reply Rate" is blank, go to **IMAP Settings** first.

---

## 📧 Sent Email Log

**Find it:** Click **Sent Log** in the top menu.

See every single person who was emailed:

- Company name
- Who received it (name + email)
- Subject line
- Status: `sent` / `failed` / `replied` / `bounced`
- Date sent

**How to use it:**

- **Search** by company name or email address
- **Filter by status** — click the status pills (e.g., show only "failed" emails)
- **Pagination** — 100 rows per page, use Next/Prev buttons

**Example:** Type "ABC Construction" to check if they were already contacted.

---

## 📈 Daily Performance Report

**Find it:** Click **Reports** in the top menu.

Day-by-day summary of your email campaigns.

| Column            | What It Means                          |
| ----------------- | -------------------------------------- |
| **Sent**          | Emails successfully delivered          |
| **Failed**        | Emails that could not be sent          |
| **Replied**       | People who wrote back _(needs IMAP)_   |
| **Bounced**       | Invalid email addresses _(needs IMAP)_ |
| **Delivery Rate** | Sent ÷ (Sent + Failed)                 |
| **Reply Rate**    | Replied ÷ Sent                         |

**What to watch:**

- Delivery Rate should stay above **95%**. If it drops, your email list needs cleaning.
- Reply Rate typically ranges **2–10%** for cold email.

---

## 🔐 IMAP Settings _(Important)_

**Find it:** Click **IMAP** in the top menu.

**Why you need this:** Without IMAP, the system cannot:

- Track who replied
- Detect bounced emails
- Calculate reply rates
- Trigger follow-up sequences

### How to Add an IMAP Account

1. Click **Add IMAP Account**
2. Fill in:
   - **Email address** — your Gmail or Google Workspace address
   - **App Password** — NOT your normal password!
     - Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
     - Generate a new app password (16 characters)
     - Paste it here
   - **IMAP Server** — leave as `imap.gmail.com`
   - **IMAP Port** — leave as `993`
3. Click **Save**
4. Click **Test Connection** to verify it works

**Do this for every sender email:**

- Louis `@miraeadvisory.com`
- Melvin `@miraeadvisory.com`
- Andrew `@miraeadvisory.com`
- Main admin account

### After Adding IMAP

Click **Run Tracker** next to each account. This scans the inbox for replies and updates the system.

From then on, the tracker runs **automatically every day at 8am**.

---

## 💬 Replies

**Find it:** Click **Replies** in the top menu.

Shows all responses from recipients.

**Filter by sentiment:**

- **Positive** — interested, wants to learn more
- **Negative** — not interested
- **Neutral** — asking questions
- **Unsubscribe** — wants to opt out

> ⚠️ This page is empty until IMAP accounts are added and the tracker has run at least once.

---

## ✅ Deliverability

**Find it:** Click **Deliverability** in the top menu.

Check if your domain is properly configured for email sending.

### Run a Domain Check

1. Enter your domain: `miraeadvisory.com`
2. Click **Run Check**
3. Results appear:
   - **SPF** — should say PASS
   - **DKIM** — should say PASS _(if FAIL, contact your IT admin)_
   - **DMARC** — should say PASS
   - **Health Score** — aim for 90+

**If DKIM shows FAIL:**

- Log in to Google Workspace Admin
- Go to **Apps → Google Workspace → Gmail → Authenticate email**
- Turn on DKIM and click **Start authentication**
- Wait 1–2 hours, then re-check

---

## 📁 Leads

**Find it:** Click **Leads** in the top menu.

Browse all lead files. Each card shows:

- Filename
- Stage (leadgen → enriched → verified → outreach)
- Number of rows
- How many have email addresses

**Click any file** to see the full table of companies.

---

## 🚀 Outreach

**Find it:** Click **Outreach** in the top menu.

Control your email campaigns.

| Button         | When to Use                                      |
| -------------- | ------------------------------------------------ |
| **Pause**      | Stop sending emails (e.g., before a holiday)     |
| **Resume**     | Re-enable daily sending                          |
| **Send Now**   | Trigger an immediate send (respects daily limit) |
| **Skip Today** | Skip today's scheduled run                       |

**Watchdog Banner:** If you see a red banner saying "3+ consecutive failures," the campaign auto-paused. Check your SMTP settings, then click **Resume**.

---

## 🧙 Sequence Wizard

**Find it:** Click **Outreach** → **+ New Sequences**

Generate a new batch of emails from a lead file.

**Steps:**

1. Select a lead file from the dropdown
2. Enter your **sender name**
3. Optionally name the campaign
4. Click **Generate Sequences**
5. The system creates a sequence file and emails start sending at the next 8am run

> ⚠️ The wizard does NOT send emails immediately. It prepares them for the daily cron.

---

## ❓ Common Questions

**Q: Why is Reply Rate empty?**  
A: You haven't added IMAP accounts yet. See Section 6 above.

**Q: Why is the Replies page empty?**  
A: Same reason — no IMAP accounts, or the tracker hasn't run yet.

**Q: How do I know if emails are sending?**  
A: Check **Dashboard** → Emails Sent, or **Daily Reports** for day-by-day numbers.

**Q: Can I see WHO was emailed?**  
A: Yes — go to **Sent Log** and search by company name or email.

**Q: What do I do if the campaign says "exhausted"?**  
A: Tell Mirae Advisory to generate new sequences or run a fresh lead search.

**Q: Is my data safe?**  
A: Yes. The portal uses password protection, CSRF tokens on all actions, and IMAP passwords are stored with root-only file permissions.

---

## 📞 Need Help?

Contact Mirae Advisory or message the Telegram bot: **@miraeclawbot**

_Last updated: May 4, 2026_
