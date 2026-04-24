# SG-Outreach Patch Notes

## 2026-04-19

### Added
- **MEDNEFITS_VARIANT** warm-intro template in `references/sequence_templates.py`
  - Uses placeholders: `{{decision_maker_name}}`, `{{company_name}}`, `{{sender_name}}`, `{{booking_link}}`
  - Registered in `VARIANTS["mednefits_variant"]`
  - Primary subject: `Employee benefits for {{company_name}}` (4 words, Gong-optimized)
  - Fallback subject: `Simplifying employee benefits for {{company_name}}`
- **Telegram OAuth recovery hooks** in `scripts/gmail_sender.py`
  - `--generate-auth-url` — prints OAuth2 sign-in URL for bot to send to user
  - `--exchange-code <code>` — exchanges OAuth2 code for token and saves it
  - Enables `/refresh_gmail` style bot flows without CLI access

### Changed
- **Auth method:** Reverted from SMTP/App Password back to **Gmail API OAuth2**
  - SMTP/App Password approach required 2FA which the account does not have
  - SendGrid integration was explored but free-tier deliverability concerns ruled it out
  - Gmail API gives best deliverability for B2B cold outreach from personal Gmail
- **SKILL.md** updated to match Gmail API sender
  - Removed all App Password references
  - Documented OAuth token recovery flow (`--generate-auth-url` → `--exchange-code`)
  - Added Mednefits variant usage instructions
  - Restored `credentials/client_secret.json` and `.gmail_token.json` references
- **Default daily limit** set to 450 (Gmail API personal account limit)

### Fixed
- `.auth_status.json` now written by both `check_auth()` and `get_auth_service()`
  - Bot can read auth health without executing a send
  - Clear `AUTH_FAILED` sentinel messages for Telegram alerting

### Known Issues
- OAuth app (`sg-outreach-492613`) remains in **Google Cloud Testing mode**
  - Refresh tokens expire after ~7 days
  - **Workaround:** Telegram bot recovery flow (`--generate-auth-url` + `--exchange-code`)
  - **Permanent fix:** Publish OAuth app to "In production" in Google Cloud Console (requires privacy policy link, one-time setup)

### Files Modified
- `scripts/gmail_sender.py` — restored Gmail API, added auth recovery flags
- `references/sequence_templates.py` — added MEDNEFITS_VARIANT
- `SKILL.md` — updated auth docs, added Mednefits instructions
- `requirements.txt` — restored Google API dependencies

### Synced To
- `/root/sg-skills-20260416/sg-outreach/` — all files mirrored
