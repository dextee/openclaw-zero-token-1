# Ultimate Prompt: Kimi Chat Agent — PDF Design

Copy and paste the entire block below into Kimi Chat (web or app).

---

```
You are a professional document designer and PDF creator. I need you to turn the following customer guide into a beautifully designed, branded PDF document.

## BRAND IDENTITY

**Company:** Mirae Advisory
**Industry:** Singapore-based SME financing / B2B lead generation
**Brand Colors:**
- Primary: Amber/Gold (#f59e0b, #d97706)
- Dark background: #09090b (near-black)
- Card background: #18181b
- Text: #f4f4f5 (off-white), #a1a1aa (muted gray)
- Success: #10b981 (emerald green)
- Warning: #f59e0b (amber)
- Danger: #ef4444 (red)

**Tone:** Professional, modern, fintech-clean, trustworthy, Singapore corporate

## DESIGN REQUIREMENTS

1. **Format:** A4 portrait PDF, ready for print and digital share
2. **Cover Page:**
   - Large "Mirae Advisory Portal" title in bold amber
   - Subtitle: "Customer Quick Start Guide"
   - Date: May 2026
   - Clean geometric pattern or abstract network/finance motif in dark background
   - Mirae Advisory logo placeholder (circle with "M" or leave space)

3. **Table of Contents:** Clickable/navigable sections with page numbers

4. **Section Headers:**
   - Large, bold, amber-colored
   - Icon beside each section (use emoji or simple line icons)
   - Subtle divider line below

5. **Body Content:**
   - Clean sans-serif font (Inter, Helvetica, or similar)
   - 11–12pt body text, #f4f4f5 on #18181b dark cards
   - Tables with alternating row colors (zinc-800 / zinc-900)
   - Callout boxes for tips, warnings, and important notes
   - Code/monospace styling for URLs, usernames, and technical terms

6. **Visual Elements:**
   - Screenshot placeholders labeled "[Portal Screenshot: Dashboard]"
   - Step-by-step numbered instructions with clear visual hierarchy
   - Info boxes with icons for "Tip", "Warning", and "Note"
   - Page numbers in footer
   - "Mirae Advisory | Confidential" in footer

7. **Special Sections:**
   - **Quick Reference Card** (last page): One-page cheat sheet with all URLs, logins, and emergency contacts

## CONTENT TO INCLUDE

Use the following content exactly, but redesign it professionally:

---

### Section 1: Access the Portal
**URL:** http://mirae-portal.loca.lt
**Login:** Basic auth popup
- Username: admin
- Password: (provided separately)
Click Logout in top-right when done.

### Section 2: Dashboard
Your homepage. Shows:
- Total Leads — companies in database
- Emails Sent — total outreach delivered
- Reply Rate — % who replied (empty until IMAP added)

Tip: If Reply Rate is blank, go to IMAP Settings first.

### Section 3: Sent Email Log
Menu: Sent Log
See every person emailed:
- Company name
- Recipient name + email
- Subject line
- Status: sent / failed / replied / bounced
- Date sent

How to use:
- Search by company or email
- Filter by status (click pills)
- 100 rows per page

### Section 4: Daily Performance Report
Menu: Reports
Day-by-day campaign summary.

| Column | Meaning |
| Sent | Successfully delivered |
| Failed | Could not send |
| Replied | Wrote back (needs IMAP) |
| Bounced | Invalid email (needs IMAP) |
| Delivery Rate | Sent / (Sent + Failed) |
| Reply Rate | Replied / Sent |

Watch: Delivery Rate >95%. Reply Rate 2-10%.

### Section 5: IMAP Settings (CRITICAL)
Menu: IMAP
Without IMAP, the system CANNOT:
- Track replies
- Detect bounces
- Calculate reply rates
- Trigger follow-ups

How to Add IMAP Account:
1. Click Add IMAP Account
2. Fill in:
   - Email address (Gmail / Google Workspace)
   - App Password (NOT normal password!)
     → Go to myaccount.google.com/apppasswords
     → Generate 16-char app password
     → Paste it here
   - IMAP Server: imap.gmail.com
   - IMAP Port: 993
3. Click Save
4. Click Test Connection

Do this for every sender email.

After adding: Click Run Tracker for each account. From then on, tracker runs automatically at 8am daily.

### Section 6: Replies
Menu: Replies
Shows all recipient responses.

Filter by sentiment:
- Positive — interested
- Negative — not interested
- Neutral — questions
- Unsubscribe — opt out

Warning: Empty until IMAP accounts added and tracker has run.

### Section 7: Deliverability
Menu: Deliverability
Check domain configuration for email sending.

Run Domain Check:
1. Enter domain: miraeadvisory.com
2. Click Run Check
3. Check results:
   - SPF = PASS
   - DKIM = PASS (if FAIL, contact IT admin)
   - DMARC = PASS
   - Health Score = 90+

If DKIM FAILS:
- Log in to Google Workspace Admin
- Apps → Google Workspace → Gmail → Authenticate email
- Turn on DKIM, click Start authentication
- Wait 1-2 hours, re-check

### Section 8: Outreach Controls
Menu: Outreach

| Button | Use When |
| Pause | Stop sending (e.g., holiday) |
| Resume | Re-enable daily sending |
| Send Now | Immediate send (respects limit) |
| Skip Today | Skip today's run |

Watchdog: Red banner = 3+ failures. Campaign auto-paused. Fix SMTP, then Resume.

### Section 9: Common Questions
Q: Why is Reply Rate empty?
A: No IMAP accounts added yet.

Q: Why is Replies page empty?
A: No IMAP, or tracker hasn't run.

Q: How do I know emails are sending?
A: Check Dashboard → Emails Sent or Daily Reports.

Q: Can I see WHO was emailed?
A: Yes — Sent Log, search by company or email.

Q: Campaign says "exhausted"?
A: Tell Mirae Advisory to generate new sequences.

Q: Is my data safe?
A: Yes. Password protection, CSRF tokens, root-only file permissions for credentials.

### Section 10: Quick Reference Card (last page)
- Portal URL: http://mirae-portal.loca.lt
- Username: admin
- Password: (provided separately)
- Telegram Bot: @miraeclawbot
- Support: Contact Mirae Advisory
- Daily Send Time: 8:00 AM SGT
- IMAP Required For: Reply tracking, bounce detection, follow-ups

---

## OUTPUT REQUIREMENTS

1. Generate the complete PDF design as a single downloadable file
2. Use professional typography and spacing
3. Ensure all tables are readable and well-formatted
4. Add visual hierarchy with headers, subheaders, and body text
5. Include page numbers and footer branding
6. The PDF should feel like a premium fintech product guide

If you cannot generate a PDF directly, provide:
- Complete HTML/CSS code that I can convert to PDF
- Or a structured markdown with precise styling instructions
- Or instructions for generating it via a tool like WeasyPrint, Puppeteer, or python-pdf

Please begin designing now.
```

---

## How to Use This Prompt

1. **Copy** everything between the triple backticks (including the opening ` ``` ` and closing ` ``` `)
2. **Paste** into Kimi Chat (web: kimi.moonshot.cn or app)
3. **Send** and wait for the agent to generate the PDF or HTML/CSS design
4. **Download** or copy the output

## If Kimi Cannot Generate PDF Directly

Kimi Chat may not have native PDF generation. In that case, ask it to output:

**Option A:** HTML + CSS (you convert via browser print-to-PDF)  
**Option B:** Markdown with precise styling notes (you convert via pandoc or similar)  
**Option C:** Step-by-step instructions to generate using a Python script

If you need me to build a Python script that converts the guide to PDF using `weasyprint` or `reportlab`, I can do that directly in this environment.
