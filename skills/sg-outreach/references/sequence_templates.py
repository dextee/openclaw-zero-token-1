"""Email sequence templates for B2B cold outreach.

Production-grade templates optimized using data from:
- Gong.io (25M+ cold emails analyzed)
- Josh Braun (interest-based CTA framework, 2x response rate)
- Alex Berman (3C framework: Complement → Case Study → CTA)
- Nick Saraev (cold reading personalization)

Key optimizations vs previous version:
- Zero product/service pitching in any email (Gong: mentioning solution = -57% replies)
- All emails ≤100 words (Gong: 3-4 sentences optimal, ~50-90 words)
- Subject lines 2-5 words, no buzzwords (Gong: long subjects = -17.9% opens)
- Interest-based CTAs only (Braun: "Worth exploring?" beats "Can we book?" by 2x)
- Cold reading openings: "I noticed...", "Looks like...", "It seems..." (Saraev)

All templates use {{double_curly}} placeholders filled at runtime.

THIS FILE CONTAINS ONLY THE MIRAE ADVISORY FINANCING TEMPLATE.
All other variants have been removed per client request.
"""

# ── Spam word list ────────────────────────────────────────────────────────────

SPAM_WORDS = [
    "free", "guaranteed", "no obligation", "act now", "limited time",
    "click here", "buy now", "earn money", "make money", "urgent",
    "once in a lifetime", "risk free", "100% free", "act immediately",
]

# ── Mirae Advisory Financing Variant ──────────────────────────────────────────
# This is the ONLY template in use. Subjects rotate deterministically.

FINANCING_VARIANT = {
    "email_number": 1,
    "subjects": [
        "Need Business Financing? We Compare Lenders So You Don't Have To",
        "Tired of Bank Rejections? We Find the Right Financing for You",
    ],
    "body": (
        "Hi {{first_name}},\n\n"
        "Mirae Advisory here — we are a Singapore-based SME financing firm led by former bankers. "
        "We help businesses like {{company_name}} get the right funding without the run-around.\n\n"
        "We offer:\n"
        "- Working Capital Loan\n"
        "- Trade Lines\n"
        "- Invoice Factoring\n"
        "- Revenue Based Financing\n"
        "- Property Backed Loan\n"
        "- Personal Loan\n\n"
        "Quick question: is {{company_name}} looking to expand or optimize your funding setup in the next 6 months?\n\n"
        "If yes, grab a 15-min slot here and we'll walk you through what you'd likely qualify for — no obligation:\n"
        "https://calendar.app.google/Vt8th4ByKcCxD4Fv6\n\n"
        "Mirae Advisory | miraeadvisory.com\n"
        "One Raffles Place Mall, #02-01, Singapore 048616\n"
        "Unsubscribe: {{unsubscribe_url}}"
    ),
    # Follow-up email (#2)
    "followup_subjects": [
        "Quick follow-up",
        "{{company_name}}",
    ],
    "followup_body": (
        "Hi {{first_name}},\n\n"
        "Quick follow-up. An {{industry}} business in {{area}} we recently helped was turned down by 3 banks "
        "before we matched them with an alternative lender. Their rate ended up 1.2% lower than what their "
        "usual bank offered.\n\n"
        "Same business, same financials — just the right lender.\n\n"
        "Worth a brief call to see what's available for {{company_name}}?\n\n"
        "Mirae Advisory | miraeadvisory.com\n"
        "One Raffles Place Mall, #02-01, Singapore 048616\n"
        "Unsubscribe: {{unsubscribe_url}}"
    ),
    # Breakup / last-chance email (#3+)
    "breakup_subjects": [
        "Last one",
        "{{company_name}}",
    ],
    "breakup_body": (
        "Hi {{first_name}},\n\n"
        "Last note from me. If {{company_name}} ever needs help comparing lenders or exploring financing options, "
        "my door's open.\n\n"
        "Best of luck to you and the team in {{area}}.\n\n"
        "Mirae Advisory | miraeadvisory.com\n"
        "One Raffles Place Mall, #02-01, Singapore 048616\n"
        "Unsubscribe: {{unsubscribe_url}}"
    ),
}

# ── Tier Templates (scheduling structure only) ────────────────────────────────
# All tier email bodies are overridden by the financing variant above.
# These remain for send_delay_days and email_count configuration.

TIER_A = {
    "name": "Aggressive",
    "email_count": 3,
    "gaps": [0, 3, 3],
    "emails": [
        {"email_number": 1, "send_delay_days": 0, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 2, "send_delay_days": 3, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 3, "send_delay_days": 3, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
    ],
}

TIER_B = {
    "name": "Nurture",
    "email_count": 5,
    "gaps": [0, 4, 4, 4, 4],
    "emails": [
        {"email_number": 1, "send_delay_days": 0, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 2, "send_delay_days": 4, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 3, "send_delay_days": 4, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 4, "send_delay_days": 4, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 5, "send_delay_days": 4, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
    ],
}

TIER_C = {
    "name": "Slow Burn",
    "email_count": 7,
    "gaps": [0, 5, 5, 5, 5, 5, 5],
    "emails": [
        {"email_number": 1, "send_delay_days": 0, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 2, "send_delay_days": 5, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 3, "send_delay_days": 5, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 4, "send_delay_days": 5, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 5, "send_delay_days": 5, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 6, "send_delay_days": 5, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
        {"email_number": 7, "send_delay_days": 5, "sequence_variant": "financing_variant", "subjects": [""], "body": ""},
    ],
}

# ── Registry ──────────────────────────────────────────────────────────────────

TIERS = {
    "A": TIER_A,
    "B": TIER_B,
    "C": TIER_C,
}

VARIANTS = {
    "financing_variant": FINANCING_VARIANT,
}
