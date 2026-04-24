# Google Dork Templates — Singapore Lead Generation

## Core Syntax Rules
- `site:` — restrict to specific domain
- `intitle:` — keyword must be in page title
- `intext:` — keyword must be in page body
- `filetype:` — restrict to file type (pdf, xlsx, csv)
- `"phrase"` — exact phrase match
- `-word` — exclude word
- `OR` — either term
- `*` — wildcard

---

## Tier 1: Singapore Directory Dorks

### Yellow Pages SG (150,000+ listings)
```
site:yellowpages.com.sg "[INDUSTRY]"
site:yellowpages.com.sg "[INDUSTRY]" "email"
site:yellowpages.com.sg intitle:"[INDUSTRY]" singapore
site:yellowpages.com.sg "[INDUSTRY]" "phone" "address"
```

### SGP Directory (2M+ entities)
```
site:sgpdirectory.com "[INDUSTRY]"
site:sgpdirectory.com "[INDUSTRY]" "Pte Ltd"
site:sgpdirectory.com "[INDUSTRY]" "contact"
```

### Yelu.sg (local business reviews)
```
site:yelu.sg "[INDUSTRY]" Singapore
site:yelu.sg "[INDUSTRY]" Singapore "review"
```

### Singapore Business Directory
```
site:singaporebusinessdirectory.com "[INDUSTRY]"
site:sgbiz.biz "[INDUSTRY]"
```

---

## Tier 2: Corporate Website Dorks

### Singapore Companies (Pte Ltd)
```
"[INDUSTRY]" "Pte Ltd" Singapore
"[INDUSTRY]" "Pte. Ltd." Singapore
"[INDUSTRY]" "Pte Ltd" site:.com.sg
"[INDUSTRY]" company Singapore email
```

### LinkedIn Companies
```
site:linkedin.com/company "[INDUSTRY]" Singapore
site:linkedin.com/company "[INDUSTRY]" "Singapore" "employees"
```

### Crunchbase
```
site:crunchbase.com/organization "[INDUSTRY]" Singapore
site:crunchbase.com "[INDUSTRY]" headquarters Singapore
```

---

## Tier 3: Government & Association Dorks

### GeBIZ (Government tenders)
```
site:gebiz.gov.sg "[INDUSTRY]"
site:gebiz.gov.sg "[INDUSTRY]" "award"
```

### SPRING/Enterprise Singapore
```
site:enterprisesingapore.gov.sg "[INDUSTRY]"
site:sgunited.gov.sg "[INDUSTRY]" companies
```

### Trade Associations
```
"[INDUSTRY]" association Singapore members
"[INDUSTRY]" chamber of commerce Singapore
site:asme.org.sg "[INDUSTRY]"
site:scf.org.sg "[INDUSTRY]"
```

### ACRA Registered
```
site:bizfile.gov.sg "[INDUSTRY]"
"[INDUSTRY]" UEN Singapore
```

---

## Tier 4: Contact Signal Dorks

### Email Discovery
```
"[INDUSTRY]" Singapore "@email.com" OR "@gmail.com" OR "@yahoo.com.sg"
"[INDUSTRY]" Singapore "contact us" OR "enquiry" OR "sales@"
"[INDUSTRY]" Singapore filetype:pdf "email"
```

### Social Media
```
site:facebook.com "[INDUSTRY]" Singapore
site:instagram.com "[INDUSTRY]" Singapore
```

---

## Execution Tips

1. **URL encode** all special characters when navigating via browser
2. **Extract result URLs** — not just snippets — for follow-up scraping
3. **Track which dorks yield results** — skip empty ones in future runs
4. **Combine with industry synonyms** — e.g., "F&B" OR "restaurant" OR "cafe"
5. **Use wildcard** for partial matches: `"[INDUSTRY]" * Singapore`
