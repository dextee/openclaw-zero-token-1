"""
industry_synonyms.py — SG B2B industry keyword expansion + SSIC code mapping.

Usage:
    from industry_synonyms import expand_industry, ssic_codes_for, is_unknown_industry, suggest_industries

    expand_industry("F&B SME")      → ["food and beverage", "restaurant", "cafe", ...]
    ssic_codes_for("construction")  → ["41", "42", "43"]
    is_unknown_industry("widgets")  → True   (triggers bot clarification flow)
    suggest_industries()            → ["F&B", "construction", "tech", ...]
"""
import re

INDUSTRY_SYNONYMS: dict[str, list[str]] = {
    # ── Food & Beverage (SSIC 56, 10, 11) ────────────────────────────────────
    "F&B":                  ["food and beverage", "restaurant", "cafe", "catering", "bakery", "coffee shop", "food services"],
    "F&B SME":              ["food and beverage", "restaurant", "cafe", "catering", "bakery"],
    "restaurant":           ["restaurant", "dining", "eatery", "food services"],
    "cafe":                 ["cafe", "coffee shop", "bistro", "brunch cafe"],
    "catering":             ["catering", "food catering", "event catering", "corporate catering"],
    "bakery":               ["bakery", "patisserie", "confectionery", "bakeshop"],
    "food manufacturing":   ["food manufacturer", "food processing", "food production"],
    "beverage":             ["beverage company", "beverage manufacturer", "drinks brand"],
    # ── Finance, Wealth & Advisory (SSIC 64, 65, 66, 69) ─────────────────────
    "family office":        ["family office", "multi family office", "single family office", "private wealth"],
    "wealth management":    ["wealth management", "private banking", "private wealth", "asset management"],
    "private banking":      ["private bank", "private banking", "wealth management"],
    "asset management":     ["asset management", "investment management", "fund management"],
    "hedge fund":           ["hedge fund", "alternative investment", "private equity"],
    "insurance":            ["insurance", "insurance broker", "insurance agency", "insurtech"],
    "fintech":              ["fintech", "financial technology", "digital payments", "payment platform"],
    "financial advisory":   ["financial advisory", "investment advisory", "financial planner", "IFA"],
    "accounting":           ["accounting firm", "auditor", "audit firm", "tax advisory"],
    "legal":                ["law firm", "legal services", "legal advisory", "lawyer"],
    "law firm":             ["law firm", "legal practice", "solicitors"],
    # ── Construction & Real Estate (SSIC 41, 42, 43, 68) ─────────────────────
    "construction":         ["construction", "contractor", "civil engineering", "builder", "general contractor"],
    "interior design":      ["interior design", "ID firm", "interior fitting", "renovation contractor"],
    "architecture":         ["architecture firm", "architect", "architectural design"],
    "real estate":          ["real estate", "property developer", "property agency"],
    "property development": ["property developer", "real estate developer", "property development"],
    "property management":  ["property management", "estate management", "facility management"],
    "M&E":                  ["M&E contractor", "mechanical and electrical", "MEP contractor"],
    "civil engineering":    ["civil engineering", "civil engineer", "infrastructure contractor"],
    # ── Technology & Software (SSIC 62, 63, 61) ──────────────────────────────
    "tech":                 ["technology", "software", "SaaS", "IT services", "tech consulting"],
    "software":             ["software", "SaaS", "software development", "application development"],
    "SaaS":                 ["SaaS", "software as a service", "cloud software"],
    "IT services":          ["IT services", "IT consulting", "managed IT", "IT solutions"],
    "cybersecurity":        ["cybersecurity", "information security", "infosec", "cyber"],
    "data analytics":       ["data analytics", "data science", "business intelligence", "BI"],
    "AI":                   ["artificial intelligence", "AI", "machine learning", "ML"],
    "blockchain":           ["blockchain", "crypto", "web3", "digital assets"],
    "telecom":              ["telecommunications", "telco", "network provider"],
    # ── Manufacturing (SSIC 10–33) ────────────────────────────────────────────
    "manufacturing":        ["manufacturer", "manufacturing", "industrial", "factory"],
    "precision engineering":["precision engineering", "precision manufacturing", "precision components"],
    "electronics":          ["electronics manufacturer", "electronics", "semiconductor"],
    "pharmaceutical":       ["pharmaceutical", "biotech", "life sciences"],
    "chemicals":            ["chemical manufacturer", "specialty chemicals", "petrochemical"],
    "machinery":            ["machinery", "industrial equipment", "machine tools"],
    # ── Professional Services (SSIC 69, 70, 71, 73, 74, 78) ──────────────────
    "consulting":           ["management consulting", "business consulting", "strategy consulting"],
    "HR":                   ["HR consulting", "recruitment", "staffing", "human resources"],
    "recruitment":          ["recruitment agency", "executive search", "staffing"],
    "marketing":            ["marketing agency", "digital marketing", "advertising agency"],
    "advertising":          ["advertising agency", "creative agency", "brand agency"],
    "PR":                   ["PR agency", "public relations", "communications agency"],
    "engineering":          ["engineering firm", "engineering consultancy", "engineering services"],
    # ── Retail & E-commerce (SSIC 47, 46) ────────────────────────────────────
    "retail":               ["retail", "retailer", "specialty store"],
    "e-commerce":           ["e-commerce", "online retail", "online store", "ecommerce"],
    "fashion":              ["fashion brand", "fashion retail", "apparel"],
    "beauty":               ["beauty brand", "cosmetics", "skincare", "personal care"],
    "jewellery":            ["jewellery", "jeweller", "fine jewellery"],
    # ── Healthcare (SSIC 86, 87, 21) ─────────────────────────────────────────
    "healthcare":           ["healthcare provider", "medical clinic", "hospital", "healthcare services"],
    "clinic":               ["medical clinic", "specialist clinic", "GP clinic", "dental clinic"],
    "medical devices":      ["medical devices", "medtech", "medical technology"],
    "dental":               ["dental clinic", "dentist", "dental practice"],
    "wellness":             ["wellness", "spa", "health and wellness"],
    # ── Logistics & Trade (SSIC 49, 50, 51, 52, 46) ──────────────────────────
    "logistics":            ["logistics", "freight", "3PL", "supply chain"],
    "freight":              ["freight forwarder", "shipping", "ocean freight", "air freight"],
    "warehousing":          ["warehousing", "storage", "distribution center", "fulfillment"],
    "trading":              ["trading company", "commodity trading", "import export"],
    "wholesale":            ["wholesale", "wholesaler", "distributor"],
    "shipping":             ["shipping company", "shipping line", "maritime"],
    # ── Hospitality, Travel & Events (SSIC 55, 79, 82) ───────────────────────
    "hospitality":          ["hotel", "resort", "hospitality", "serviced apartment"],
    "hotel":                ["hotel", "luxury hotel", "boutique hotel"],
    "events":               ["events company", "event management", "MICE", "event planning"],
    "travel":               ["travel agency", "tour operator", "DMC"],
    # ── Education (SSIC 85) ──────────────────────────────────────────────────
    "education":            ["education", "tuition centre", "preschool", "training provider"],
    "tuition":              ["tuition centre", "enrichment centre", "education services"],
    "preschool":            ["preschool", "childcare", "kindergarten", "early childhood"],
    "edtech":               ["edtech", "education technology", "online learning"],
    "training":             ["corporate training", "training provider", "professional development"],
    # ── Creative & Media (SSIC 18, 58, 59, 60, 74, 90) ───────────────────────
    "design":               ["design studio", "graphic design", "product design"],
    "media":                ["media company", "publishing", "production house"],
    "film":                 ["film production", "video production", "production studio"],
    "photography":          ["photography studio", "photographer", "commercial photography"],
    # ── Energy, Environment & Utilities (SSIC 35–39) ─────────────────────────
    "energy":               ["energy company", "oil and gas", "petroleum"],
    "renewable":            ["renewable energy", "solar", "clean energy", "sustainability"],
    "sustainability":       ["sustainability consultancy", "ESG advisory", "green tech"],
    "utilities":            ["utilities provider", "water utility", "waste management"],
    # ── Vague "SME" alone — bot should ask which sector ──────────────────────
    "SME":                  [],
}

SSIC_CODES: dict[str, list[str]] = {
    "F&B":                  ["56"],
    "F&B SME":              ["56"],
    "restaurant":           ["56"],
    "cafe":                 ["56"],
    "catering":             ["56"],
    "bakery":               ["56", "10"],
    "food manufacturing":   ["10"],
    "beverage":             ["11"],
    "family office":        ["64", "66"],
    "wealth management":    ["64", "66"],
    "private banking":      ["64"],
    "asset management":     ["64", "66"],
    "hedge fund":           ["64", "66"],
    "insurance":            ["65"],
    "fintech":              ["64", "66", "62"],
    "financial advisory":   ["66"],
    "accounting":           ["69"],
    "legal":                ["69"],
    "law firm":             ["69"],
    "construction":         ["41", "42", "43"],
    "interior design":      ["43", "71"],
    "architecture":         ["71"],
    "real estate":          ["68"],
    "property development": ["41", "68"],
    "property management":  ["68", "81"],
    "M&E":                  ["43"],
    "civil engineering":    ["42", "71"],
    "tech":                 ["62", "63"],
    "software":             ["62"],
    "SaaS":                 ["62"],
    "IT services":          ["62"],
    "cybersecurity":        ["62"],
    "data analytics":       ["62", "63"],
    "AI":                   ["62", "72"],
    "blockchain":           ["62", "64"],
    "telecom":              ["61"],
    "manufacturing":        ["10","11","12","13","14","15","16","17","18","19",
                             "20","21","22","23","24","25","26","27","28","29",
                             "30","31","32","33"],
    "precision engineering":["25", "26", "28"],
    "electronics":          ["26", "27"],
    "pharmaceutical":       ["21"],
    "chemicals":            ["20"],
    "machinery":            ["28"],
    "consulting":           ["70", "74"],
    "HR":                   ["78"],
    "recruitment":          ["78"],
    "marketing":            ["73"],
    "advertising":          ["73"],
    "PR":                   ["73"],
    "engineering":          ["71", "72"],
    "retail":               ["47"],
    "e-commerce":           ["47", "46"],
    "fashion":              ["47", "14"],
    "beauty":               ["47", "20"],
    "jewellery":            ["47", "32"],
    "healthcare":           ["86"],
    "clinic":               ["86"],
    "medical devices":      ["32", "26"],
    "dental":               ["86"],
    "wellness":             ["96", "86"],
    "logistics":            ["49", "50", "51", "52", "53"],
    "freight":              ["49", "50", "51", "52"],
    "warehousing":          ["52"],
    "trading":              ["46"],
    "wholesale":            ["46"],
    "shipping":             ["50"],
    "hospitality":          ["55"],
    "hotel":                ["55"],
    "events":               ["82", "93"],
    "travel":               ["79"],
    "education":            ["85"],
    "tuition":              ["85"],
    "preschool":            ["85"],
    "edtech":               ["85", "62"],
    "training":             ["85"],
    "design":               ["74", "18"],
    "media":                ["58", "59", "60"],
    "film":                 ["59"],
    "photography":          ["74"],
    "energy":               ["35"],
    "renewable":            ["35"],
    "sustainability":       ["70", "74"],
    "utilities":            ["35", "36", "37", "38", "39"],
}


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("&", "and").strip())


def expand_industry(raw_input: str) -> list[str]:
    """Return search-friendly synonym list. Unknown input → [raw_input] passthrough."""
    key = _normalize(raw_input)
    # 1. Exact match (normalized)
    for known, syns in INDUSTRY_SYNONYMS.items():
        if _normalize(known) == key:
            return syns if syns else [raw_input]
    # 2. Bidirectional substring
    for known, syns in INDUSTRY_SYNONYMS.items():
        nk = _normalize(known)
        if nk and (nk in key or key in nk):
            return syns if syns else [raw_input]
    # 3. Match against synonym values
    for known, syns in INDUSTRY_SYNONYMS.items():
        for syn in syns:
            if _normalize(syn) == key:
                return syns
    return [raw_input]


def ssic_codes_for(raw_input: str) -> list[str]:
    """Return ACRA SSIC 2-digit prefixes. Unknown → []."""
    key = _normalize(raw_input)
    for known, codes in SSIC_CODES.items():
        if _normalize(known) == key:
            return codes
    for known, codes in SSIC_CODES.items():
        nk = _normalize(known)
        if nk and (nk in key or key in nk):
            return codes
    return []


def is_unknown_industry(raw_input: str) -> bool:
    """True when we can't map the input — bot should ask which sector."""
    result = expand_industry(raw_input)
    return result == [raw_input]


def suggest_industries() -> list[str]:
    return ["F&B", "construction", "tech", "family office", "wealth management",
            "healthcare", "education", "logistics", "manufacturing", "real estate"]


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "F&B SME"
    print(f"Input:    {query!r}")
    print(f"Synonyms: {expand_industry(query)}")
    print(f"SSIC:     {ssic_codes_for(query)}")
    print(f"Unknown:  {is_unknown_industry(query)}")
