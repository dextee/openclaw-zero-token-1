# Deduplication & Scoring Algorithm

## Deduplication

### Normalize Before Comparison

```python
import re
from thefuzz import fuzz  # or implement simple ratio

def normalize_phone(phone):
    """Strip all non-digits, remove leading 65 for SG numbers."""
    digits = re.sub(r'[^0-9]', '', phone)
    if digits.startswith('65') and len(digits) > 8:
        digits = digits[2:]
    return digits

def normalize_domain(url):
    """Extract bare domain from URL."""
    url = url.lower().strip()
    url = re.sub(r'^https?://', '', url)
    url = re.sub(r'^www\.', '', url)
    url = re.sub(r'/.*$', '')
    return url

def normalize_company(name):
    """Lowercase, strip punctuation, collapse whitespace."""
    name = name.lower().strip()
    name = re.sub(r'[\.,\-\(\)]', '', name)
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'\b(pte|ltd|private|limited|corporation|inc)\b', '', name)
    return name.strip()
```

### Match Rules

Two leads are duplicates if **any** of these match:

| Field | Match Type | Threshold |
|---|---|---|
| Company name | Fuzzy string match | ≥ 0.90 similarity |
| Phone number | Exact (normalized) | 100% |
| Website domain | Exact (normalized) | 100% |
| UEN | Exact | 100% |

### Merge Strategy

When duplicates found:
1. Keep the record with **most fields populated**
2. Merge missing fields from the other record
3. Append all source URLs to `notes` field
4. Keep highest `lead_score`

---

## Scoring Model

### Signals & Points

| Signal | Points | How to verify |
|---|---|---|
| Verified email (tested or explicit) | 25 | Found on website contact page or email pattern confirmed |
| Verified phone | 15 | Active phone number, not placeholder |
| ACRA verified (active status) | 20 | BizFile shows "Registered" / "Live" |
| LinkedIn company page exists | 10 | Company search returns LinkedIn page |
| Website has contact page | 10 | `/contact` or `/about` page exists with form/email |
| Decision maker identified | 15 | Name + title found via LinkedIn or website team page |
| Recent activity (updated < 6 months) | 5 | Website footer shows recent copyright/news |

### Classification

| Tier | Score | Description | Action |
|---|---|---|---|
| **Hot** | 70+ | Verified contact + legal entity | Prioritize for outreach |
| **Warm** | 40-69 | Partial contact info | Needs enrichment |
| **Cold** | < 40 | Basic directory listing only | Queue for bulk outreach |

### Quick Score Examples

**Hot Lead (85):**
```
Acme Logistics Pte Ltd
- Phone: +65 6123 4567 ✓ (15)
- Email: sales@acme-logistics.com.sg ✓ (25)
- ACRA: Active, UEN 201234567K ✓ (20)
- LinkedIn: /company/acme-logistics ✓ (10)
- Decision maker: John Tan, Director ✓ (15)
Score: 85 → HOT
```

**Warm Lead (50):**
```
Beta Foods Pte Ltd
- Phone: +65 6987 6543 ✓ (15)
- ACRA: Active, UEN 201987654M ✓ (20)
- Website: betafods.sg (contact page exists) ✓ (10)
- Recent: Copyright 2025 ✓ (5)
Score: 50 → WARM
```

**Cold Lead (25):**
```
Gamma Trading
- Phone: 6555 1234 ✓ (15)
- Website: gammatrading.com (no contact page) (0)
Score: 15 → COLD
```
