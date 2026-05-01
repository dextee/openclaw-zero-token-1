# Ultimate Audit Prompt — SG LeadGen Portal + Skills

Run this as a comprehensive security, functionality, and integration audit. Do not stop at surface-level checks. Test every route, every edge case, every data flow.

---

## Part 1: Portal (`/root/openclaw-zero-token/portal/`)

### 1.1 Code Review

Read every file in `portal/`:

- `main.py` — check all 17 routes for:
  - Missing input validation (path traversal, SQL injection equivalents in CSV ops)
  - Race conditions in file read/write
  - Proper auth enforcement on ALL routes (including error handlers)
  - CSRF token logic flaws
  - Memory exhaustion risks (large CSV uploads, huge page_size)
  - Missing HTTP method restrictions
- `reader.py` — check:
  - `_csv_cache` memory leak potential (unbounded dict growth)
  - `_compute_row_hash()` collision risk (only 16 chars of SHA-256)
  - Formula injection protection completeness
  - File handle leaks (files left open on exceptions)
  - `get_leads_page()` performance with 100k+ row files
- `auth.py` — check:
  - Timing attack resistance (is `secrets.compare_digest` used everywhere?)
  - Argon2 params (memory cost, time cost)
  - CSRF token entropy and rotation logic
- `templates/` — check:
  - XSS vulnerabilities (unescaped `{{ }}` in user-controlled data)
  - Missing CSRF tokens in forms
  - HTMX `hx-get` URLs that bypass auth

### 1.2 Live Functional Tests

Start the portal if not running (`systemctl status sg-portal`), then:

```bash
# Auth & security
curl -s http://127.0.0.1:3030/portal/dashboard                    # should 401
curl -s -u admin:wrongpass http://127.0.0.1:3030/portal/dashboard # should 401
curl -s -u admin:MiraePortal2026! http://127.0.0.1:3030/api/v1/health

# Data mutation with wrong CSRF
curl -s -u admin:MiraePortal2026! -X POST -d "csrf=fake" http://127.0.0.1:3030/portal/upload

# Path traversal attempt
curl -s -u admin:MiraePortal2026! -X POST -d "csrf=<real>" \
  "http://127.0.0.1:3030/portal/files/../../../../etc/passwd/delete"

# Upload oversized file
python3 -c "open('/tmp/huge.csv','w').write('a\n' + 'b\n'*200000)"
curl -s -u admin:MiraePortal2026! -F "file=@/tmp/huge.csv" -F "stage=leadgen" \
  -F "csrf=<real>" http://127.0.0.1:3030/portal/upload

# Export with malicious query (try to export all files)
curl -s -u admin:MiraePortal2026! \
  "http://127.0.0.1:3030/api/v1/export/<id>?page_size=9999999"

# HTMX partial auth bypass
curl -s -H "HX-Request: true" http://127.0.0.1:3030/portal/leads/<id>  # should 401
```

### 1.3 Performance & Stress

- Upload a 50k-row CSV. Time the upload and the first page load.
- Open the leads table with `page_size=5000`. Does it crash?
- Sort by a non-existent column. Error handling?

### 1.4 Missing Features Check

- Is there a way to bulk edit rows? (No — document this gap)
- Is there campaign creation from the portal? (No — document)
- Is there real-time lead scoring feedback? (No — document)
- Are uploaded files scanned for malware? (No — document risk)

---

## Part 2: SG Skills Pipeline (`skills/sg-leadgen/`, `sg-enrich/`, `sg-verify/`, `sg-outreach/`)

### 2.1 Data Flow Integrity

Trace a lead from generation to outreach:

1. `run_full_pipeline.py` — does it output valid CSV?
2. `dedup_score.py` — are duplicates actually removed? Test with known duplicates.
3. `enrich_contacts.py` — does it correctly extract decision makers? Test on 10 real websites.
4. `verify_emails.py` — are verification results accurate? Test with known good/bad emails.
5. `generate_sequences.py` — does it correctly inject `{{unsubscribe_url}}`? Check output CSV.
6. `workspace_smtp_sender.py` — does it respect daily limits? Test with dry-run.

### 2.2 Script Robustness

For EACH script, check:

- What happens if input CSV is missing required columns?
- What happens if disk is full during CSV write?
- What happens if network timeouts occur (enrichment/verification)?
- Are temporary files cleaned up on crash?
- Are there hardcoded paths that break if run from a different directory?

### 2.3 Cross-Skill Integration

- Does `sg-enrich` read the exact output format of `sg-leadgen`?
- Does `sg-verify` read the exact output format of `sg-enrich`?
- Does `sg-outreach` read the exact output format of `sg-verify`?
- Check column name mappings — are they case-sensitive? Do they handle `utf-8-sig` BOM?

### 2.4 Outreach System Deep Check

- `daily_outreach.sh`: Does the idempotency check work? (Run twice in same day — second should skip)
- `workspace_smtp_sender.py`: Does the domain throttle actually work? (Send to 2 @gmail.com addresses quickly)
- `setup_outreach.py`: Can the wizard be resumed mid-flow? Test by killing it at step 5 and restarting.
- `outreach_control.py`: Does cross-tenant protection actually reject wrong `--user-id`?
- `outreach_status.py`: Does `--preview-next` show the correct rows?

---

## Part 3: Configuration & State Management

### 3.1 OpenClaw Config

```bash
# Check models config
grep -c "openai-codex" .openclaw-upstream-state/openclaw.json
grep -c "deepseek-web" .openclaw-upstream-state/openclaw.json
grep -c "qwen-web" .openclaw-upstream-state/openclaw.json

# Check auth profiles
python3 -c "
import json
with open('.openclaw-upstream-state/agents/main/agent/auth-profiles.json') as f:
    p = json.load(f).get('profiles', {})
for k, v in p.items():
    print(f'{k}: type={v.get(\"type\")} expires={v.get(\"expires\", \"N/A\")}')
"
```

- Is `openai-codex:default` expired? If yes, document re-auth steps.
- Are there stale profiles that should be removed?

### 3.2 Workspace State

- `~/.openclaw/workspace/leads/` — are there orphaned `.tmp` or `.lock` files?
- `~/.openclaw/workspace/outreach/` — are user state files valid JSON?
- Check for files >30 days old that should be archived.

---

## Part 4: Security Hardening Checklist

- [ ] Portal password is NOT default/generic (change if `MiraePortal2026!`)
- [ ] Portal is not exposed to public internet without VPN/reverse proxy
- [ ] `auth-profiles.json` contains no plaintext passwords (only hashes/tokens)
- [ ] Telegram bot token is not in any committed file
- [ ] No `.env` files with secrets are committed
- [ ] Gateway token in `openclaw.json` is not the default
- [ ] `refresh-openai-codex-token.sh` log file is not world-readable
- [ ] Cron job runs as root — is this necessary? Document risk.
- [ ] `sg-outreach` suppressions list exists and is honored
- [ ] Bounce handling prevents re-sending to bad emails

---

## Part 5: Deliverables

Produce a single report with:

1. **Critical Issues** (must fix before production use)
2. **Warnings** (should fix soon)
3. **Suggestions** (nice-to-have improvements)
4. **Verified Working** list (for confidence)
5. **Test Commands** you ran (so I can reproduce)

Format as Markdown. Be specific: file names, line numbers, exact commands.
