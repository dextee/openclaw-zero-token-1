# SG Outreach — End-to-End Telegram Testing Guide

## Before You Start

Make sure the OpenClaw gateway is running the latest skill code. If the bot mentions **"App Password"** or asks you to visit `myaccount.google.com/apppasswords`, the old skill is cached. Restart the gateway:

```bash
systemctl restart openclaw-gateway
```

Wait 30 seconds for the gateway to come back online before testing.

---

## Test 1: Auth Check (30 seconds)

**Send this in Telegram:**
```
check gmail auth
```

**Expected reply:**
```
Auth OK — arvion.sg@gmail.com
```

**If you see an error** (e.g. `AUTH_FAILED`, `token expired`, `invalid_grant`), the bot will auto-generate a sign-in link. Click it, click **Allow**, copy the code, and paste it back in Telegram. The bot will handle the rest.

---

## Test 2: Preview Emails Without Sending (1 minute)

**Send this in Telegram:**
```
dry run the first 3 mednefits outreach emails
```

**What the bot does:**
- Reads the lead sequences from the CSV
- Previews the subject lines and first lines of the email bodies
- Shows who would receive them
- **Does NOT send anything**

**Expected reply format:**
```
[DRY RUN] Email #1 → jeremy.lee@advisoryhrconsultancy.com.sg (Advisory HR Consultancy Group Pte Ltd)
  Subject: Advisory HR Consultancy Group Pte Ltd
  Body: Advisory HR Consultancy Group Pte Ltd —

Noticed Advisory HR Consultancy Group Pte Ltd runs on WordP...

[DRY RUN] Email #1 → user@domain.com (DecodeHR Pte Ltd)
  Subject: DecodeHR Pte Ltd tech
  Body: DecodeHR Pte Ltd —

Noticed DecodeHR Pte Ltd runs on WordP...

Summary: 3 emails previewed
```

---

## Test 3: Send One Real Test Email (1 minute)

**Send this in Telegram:**
```
send a test email to design@dexterng.asia with subject "Employee benefits for Dexter NG" and body "Dear Dexter, I hope you're doing well. I'm Wei Xian from Mednefits, the Flexible Employee Benefits Platform provider. Do let me know when works best for you, online or in person. Best regards, Wei Xian Mednefits"
```

**What the bot does:**
- Sends one single email via Gmail
- Updates status in the system

**Expected reply:**
```
SUCCESS: Email sent!
To: design@dexterng.asia
Subject: Employee benefits for Dexter NG
From: Wei Xian <arvion.sg@gmail.com>
```

**Check:** Open the recipient inbox (and spam folder) to confirm delivery.

---

## Test 4: Send Mednefits Sequences (Advanced — Only After Tests 1-3 Pass)

**Send this in Telegram:**
```
send the first email of the mednefits outreach sequences to the first 5 leads
```

**Or with a daily limit:**
```
send the mednefits outreach sequences with daily limit 5
```

**What the bot does:**
- Loads the sequences CSV
- Sends only Email #1 (the first touch) to the first 5 pending leads
- Respects the daily limit
- Reports back who was sent to

**Expected reply:**
```
✓ Sent #1 to jeremy.lee@advisoryhrconsultancy.com.sg (Advisory HR Consultancy Group Pte Ltd)
✓ Sent #1 to user@domain.com (DecodeHR Pte Ltd)
...
Summary:
  Sent: 5
  Failed: 0
  Daily total: 5/5
```

---

## Troubleshooting

| Problem | What to do |
|---------|-----------|
| Bot says "App Password" | Gateway is cached. Run `systemctl restart openclaw-gateway` and wait 30s. |
| Bot says "AUTH_FAILED: Token expired" | Send `check gmail auth` → bot will give you a Google sign-in link → click Allow → paste code back. |
| Bot says "No sequences file found" | The leads CSV hasn't been generated yet. Ask the bot to `generate sequences from the mednefits leads`. |
| Emails not arriving | Check spam folder. Gmail personal accounts have high deliverability, but cold email can still land in spam depending on the recipient's filters. |
| Bot is unresponsive | Check if gateway is running: `systemctl status openclaw-gateway` |

---

## Important Limits

- **Daily send limit:** 450 emails/day (Gmail hard cap). We recommend 100-150/day for outreach.
- **Rate limit:** The sender adds a 2-3 second random delay between each email.
- **Sequences:** Email #2 automatically sends 3-5 days after Email #1 (based on tier). The bot handles scheduling.

---

## What Was Changed Today (for reference)

1. **Mednefits template added** — new warm-intro email variant for HR/benefits prospects
2. **Auth restored to Gmail API OAuth2** — better deliverability than SMTP/SendGrid for B2B
3. **Telegram recovery built** — if the token expires, the bot auto-generates a sign-in link. No CLI needed.
4. **Skill docs updated** — bot now gives correct instructions for the current auth method
