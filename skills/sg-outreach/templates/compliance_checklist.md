# Outreach Compliance Checklist

## Legal Requirements

### Singapore PDPA (Personal Data Protection Act)

- **Consent required** for marketing emails. The setup wizard requires explicit PDPA confirmation.
- **Unsubscribe mechanism** must be present in every email.
- **Sender identification** must be clear (name, company, contact).

### CAN-SPAM (US, if any recipients are US-based)

- Accurate header information
- Clear subject lines
- Physical postal address in every email
- Working unsubscribe mechanism
- Honor opt-out requests within 10 business days

## Template Requirements

Every outbound email must contain:

1. **Unsubscribe link** — `{{unsubscribe_url}}` is injected at sequence generation time
2. **Physical address** — "One Raffles Place Mall, #02-01, Singapore 048616"
3. **Sender identification** — "{{sender_name}} | Mirae Advisory | miraeadvisory.com"

## Where `{{unsubscribe_url}}` is Injected

`generate_sequences.py` constructs the unsubscribe URL per recipient:

```python
unsub_url = f"mailto:unsubscribe@miraeadvisory.com?subject=Unsubscribe%20{urllib.parse.quote(to_email)}"
```

This is passed as `extra_defaults` to `fill_template()` and replaces `{{unsubscribe_url}}` in the template body.

## Footer Auto-Append (Sender Script)

`workspace_smtp_sender.py` also appends a footer via `build_footer()` if a compliance config exists at `/root/.openclaw/workspace/compliance/COMPLIANCE.json`.

The compliance footer is a **redundancy** — the template itself must already contain the required elements.

## Audit Trail

- Every send is recorded in `.outreach_history.json`
- Bounces are auto-suppressed by `suppress_bounces.py`
- Unsubscribes are processed by `process_unsubscribes.py` (weekly IMAP sweep)
- `runs.log` provides per-run audit trail
