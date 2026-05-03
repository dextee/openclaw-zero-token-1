from pathlib import Path
import asyncio, csv, hashlib, io, json, os, re, subprocess, sys
from datetime import datetime, timezone
from urllib.parse import quote_plus
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import reader
from auth import get_csrf_token, require_auth, verify_csrf_token

PORTAL_DIR = Path(__file__).parent
TEMPLATES_DIR = PORTAL_DIR / "templates"

# Load outreach modules once at startup — avoids per-request sys.path growth
sys.path.insert(0, str(Path("/root/openclaw-zero-token/skills/sg-outreach/scripts")))
import imap_auth
from deliverability_check import check_domain as _check_domain

app = FastAPI(title="SG Pipeline Portal", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Filters
templates.env.filters["fmt_int"] = lambda v: f"{int(v):,}" if str(v).isdigit() else (str(v) if v else "—")
templates.env.filters["fmt_pct"] = lambda v, d=1: f"{float(v):.{d}f}%" if v else "—"
templates.env.globals["csrf_token"] = get_csrf_token
templates.env.filters["file_id"] = lambda p: hashlib.sha256(str(p).encode()).hexdigest()[:16]
templates.env.filters["tojson"] = lambda v, indent=None: json.dumps(v, indent=indent)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_ROWS = 100_000
SKILL_BASE = Path("/root/openclaw-zero-token/skills")
LEADS_OUTPUT = Path("/root/.openclaw/workspace/leads")
OUTREACH_SCRIPTS = Path("/root/openclaw-zero-token/skills/sg-outreach/scripts")


def _file_id(path: Path) -> str:
    import hashlib
    return hashlib.sha256(str(path).encode()).hexdigest()[:16]


# ── Error Handlers ───────────────────────────────────────────────────────────

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return templates.TemplateResponse(
            "401.html",
            {"request": request, "detail": exc.detail},
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "404.html",
            {"request": request, "detail": exc.detail},
            status_code=404,
        )
    return templates.TemplateResponse(
        "500.html",
        {"request": request, "detail": str(exc.detail)},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import logging
    logging.exception("Unhandled portal exception")
    return templates.TemplateResponse(
        "500.html",
        {"request": request, "detail": "An internal error occurred."},
        status_code=500,
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return RedirectResponse("/portal/dashboard")


@app.get("/portal/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, _: str = Depends(require_auth)):
    data = reader.get_dashboard_data()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "data": data,
    })


@app.get("/portal/leads", response_class=HTMLResponse)
async def leads_browser(
    request: Request,
    uploaded: str = "",
    deleted: str = "",
    stage: str = "",
    _: str = Depends(require_auth),
):
    files = reader.list_lead_files()
    if stage:
        files = [f for f in files if f.stage == stage]
    return templates.TemplateResponse("leads_browser.html", {
        "request": request,
        "files": files,
        "uploaded": uploaded,
        "deleted": deleted,
        "stage_filter": stage,
    })


@app.get("/portal/leads/{file_id}", response_class=HTMLResponse)
async def leads_table(
    request: Request,
    file_id: str,
    q: str = "",
    sendability: str = "",
    tier: str = "",
    min_score: int = 0,
    has_email: str = "",
    sort_col: str = "",
    sort_dir: str = "asc",
    page: int = 1,
    _: str = Depends(require_auth),
):
    lead_file = reader.get_file_by_id(file_id)
    if not lead_file:
        raise HTTPException(status_code=404, detail="File not found")

    has_email_bool = None
    if has_email == "1":
        has_email_bool = True
    elif has_email == "0":
        has_email_bool = False

    page_data = reader.get_leads_page(
        lead_file,
        q=q,
        sendability=sendability,
        tier=tier,
        min_score=min_score,
        has_email=has_email_bool,
        sort_col=sort_col,
        sort_dir=sort_dir,
        page=page,
    )
    summary = reader.get_lead_summary(lead_file)

    # HTMX partial request
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/lead_rows.html", {
            "request": request,
            "rows": page_data.rows,
            "columns": page_data.columns,
            "page": page_data.page,
            "page_size": page_data.page_size,
            "total": page_data.total,
            "total_pages": page_data.total_pages,
            "file_id": file_id,
            "q": q,
            "sendability": sendability,
            "tier": tier,
            "min_score": min_score,
            "has_email": has_email,
            "sort_col": sort_col,
            "sort_dir": sort_dir,
        })

    return templates.TemplateResponse("leads_table.html", {
        "request": request,
        "lead_file": lead_file,
        "file_id": file_id,
        "rows": page_data.rows,
        "columns": page_data.columns,
        "page": page_data.page,
        "page_size": page_data.page_size,
        "total": page_data.total,
        "total_pages": page_data.total_pages,
        "file_id": file_id,
        "summary": summary,
        "q": q,
        "sendability": sendability,
        "tier": tier,
        "min_score": min_score,
        "has_email": has_email,
        "sort_col": sort_col,
        "sort_dir": sort_dir,
    })


@app.get("/portal/upload", response_class=HTMLResponse)
async def upload_form(request: Request, _: str = Depends(require_auth)):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.post("/portal/upload")
async def upload_post(
    request: Request,
    file: UploadFile = File(...),
    stage: str = Form("leadgen"),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if stage not in {"leadgen", "enriched", "verified"}:
        raise HTTPException(status_code=400, detail="Invalid stage")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files allowed")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    try:
        text = content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid CSV")

    if len(rows) > MAX_UPLOAD_ROWS + 1:
        raise HTTPException(status_code=413, detail="Too many rows (max 100k)")

    if not rows or len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSV is empty")

    # Build safe filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\-\.]", "_", file.filename)
    filename = f"{timestamp}_{safe_name}"

    # Save to correct directory
    dest_dir = LEADS_OUTPUT
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    # Path jail
    resolved = dest_path.resolve()
    if not str(resolved).startswith(str(LEADS_OUTPUT.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")

    with open(dest_path, "wb") as f:
        f.write(content)

    return RedirectResponse(f"/portal/leads?uploaded={filename}&stage={stage}", status_code=303)


@app.post("/portal/files/{file_id}/delete")
async def delete_file(
    file_id: str,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    lead_file = reader.get_file_by_id(file_id)
    if not lead_file:
        raise HTTPException(status_code=404, detail="File not found")

    resolved = lead_file.path.resolve()
    if not str(resolved).startswith(str(SKILL_BASE.resolve())) and not str(resolved).startswith(str(Path("/root/.openclaw/workspace").resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")

    try:
        lead_file.path.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse("/portal/leads?deleted=1", status_code=303)


@app.get("/portal/campaigns", response_class=HTMLResponse)
async def campaigns_list(_: str = Depends(require_auth)):
    return RedirectResponse("/portal/outreach", status_code=302)


@app.get("/portal/campaigns/{file_id}", response_class=HTMLResponse)
async def campaign_detail(request: Request, file_id: str, _: str = Depends(require_auth)):
    campaign = reader.get_campaign_by_id(file_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = reader.get_campaign_rows(campaign)
    state_path = campaign.path / "campaign_state.json"
    state = {}
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            pass

    approved = (campaign.path / "approved.json").exists()

    return templates.TemplateResponse("campaign_detail.html", {
        "request": request,
        "campaign": campaign,
        "rows": rows,
        "state": state,
        "approved": approved,
    })


@app.post("/portal/campaigns/{file_id}/approve")
async def campaign_approve(
    file_id: str,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    campaign = reader.get_campaign_by_id(file_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    approved_path = campaign.path / "approved.json"
    with open(approved_path, "w", encoding="utf-8") as f:
        json.dump({"approved_at": datetime.now(timezone.utc).isoformat()}, f)

    return RedirectResponse(f"/portal/campaigns/{file_id}", status_code=303)


@app.get("/portal/outreach", response_class=HTMLResponse)
async def outreach_dashboard(request: Request, _: str = Depends(require_auth)):
    campaigns = reader.get_active_campaigns()
    runs_log = ""
    if campaigns:
        log_path = Path("/root/.openclaw/workspace/outreach") / f"user_{campaigns[0].user_id}" / "runs.log"
        if log_path.exists():
            try:
                lines = log_path.read_text(encoding="utf-8").strip().splitlines()
                runs_log = "\n".join(reversed(lines[-14:]))
            except Exception:
                pass
    return templates.TemplateResponse("outreach.html", {
        "request": request,
        "campaigns": campaigns,
        "runs_log": runs_log,
    })


@app.post("/portal/outreach/{user_id}/pause")
async def outreach_pause(
    user_id: str,
    request: Request,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    subprocess.run(
        ["python3", str(SKILL_BASE / "sg-outreach/scripts/outreach_control.py"),
         "--pause", "--user-id", user_id, "--confirm"],
        capture_output=True, text=True, timeout=15
    )
    return RedirectResponse("/portal/outreach?msg=paused", status_code=303)


@app.post("/portal/outreach/{user_id}/resume")
async def outreach_resume(
    user_id: str,
    request: Request,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    subprocess.run(
        ["python3", str(SKILL_BASE / "sg-outreach/scripts/outreach_control.py"),
         "--resume", "--user-id", user_id, "--confirm"],
        capture_output=True, text=True, timeout=15
    )
    return RedirectResponse("/portal/outreach?msg=resumed", status_code=303)


@app.post("/portal/outreach/{user_id}/send-now")
async def outreach_send_now(
    user_id: str,
    request: Request,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    subprocess.Popen(
        ["bash", str(SKILL_BASE / "sg-outreach/scripts/daily_outreach.sh"),
         "--user-id", user_id, "--trigger", "manual"],
        env={**os.environ, "TELEGRAM_CHAT_ID": user_id},
    )
    return RedirectResponse("/portal/outreach?msg=send-now", status_code=303)


@app.post("/portal/outreach/{user_id}/skip-today")
async def outreach_skip_today(
    user_id: str,
    request: Request,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    subprocess.run(
        ["python3", str(OUTREACH_SCRIPTS / "outreach_control.py"),
         "--skip-today", "--user-id", user_id, "--confirm"],
        capture_output=True, text=True, timeout=15
    )
    return RedirectResponse("/portal/outreach?msg=skip-today", status_code=303)


@app.post("/portal/outreach/{user_id}/retry-today")
async def outreach_retry_today(
    user_id: str,
    request: Request,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    subprocess.Popen(
        ["bash", str(OUTREACH_SCRIPTS / "daily_outreach.sh"),
         "--user-id", user_id, "--trigger", "retry"],
        env={**os.environ, "TELEGRAM_CHAT_ID": user_id},
    )
    return RedirectResponse("/portal/outreach?msg=retry-today", status_code=303)


@app.get("/portal/replies", response_class=HTMLResponse)
async def replies_page(
    request: Request,
    sentiment: str = "",
    _: str = Depends(require_auth),
):
    rows = reader.get_reply_rows(sentiment_filter=sentiment)
    return templates.TemplateResponse("replies.html", {
        "request": request,
        "rows": rows,
        "sentiment_filter": sentiment,
    })


# ── Sent Email Log ───────────────────────────────────────────────────────────

@app.get("/portal/sent-log", response_class=HTMLResponse)
async def sent_log_page(
    request: Request,
    status: str = "",
    search: str = "",
    page: int = 1,
    _: str = Depends(require_auth),
):
    """Recipient-level sent email log — shows WHO was emailed."""
    rows_per_page = 100
    all_rows = []

    for seq_path in Path("/root/.openclaw/workspace/outreach").glob("user_*/sequences.csv"):
        try:
            with open(seq_path, "r", encoding="utf-8-sig") as f:
                reader_csv = csv.DictReader(f)
                for row in reader_csv:
                    all_rows.append(row)
        except Exception:
            continue

    # Filter by status
    if status:
        all_rows = [r for r in all_rows if r.get("status", "").lower() == status.lower()]

    # Filter by search (company name or email)
    if search:
        s = search.lower()
        all_rows = [r for r in all_rows if s in r.get("company_name", "").lower() or s in r.get("to_email", "").lower()]

    total = len(all_rows)
    total_pages = max(1, (total + rows_per_page - 1) // rows_per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * rows_per_page
    end = start + rows_per_page
    page_rows = all_rows[start:end]

    # Status counts for filter pills
    status_counts = {}
    for r in all_rows:
        st = r.get("status", "unknown") or "unknown"
        status_counts[st] = status_counts.get(st, 0) + 1

    return templates.TemplateResponse("sent_log.html", {
        "request": request,
        "rows": page_rows,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "status_filter": status,
        "search": search,
        "status_counts": status_counts,
    })


# ── Daily Performance Report ─────────────────────────────────────────────────

@app.get("/portal/reports", response_class=HTMLResponse)
async def daily_report_page(request: Request, _: str = Depends(require_auth)):
    """Day-over-day performance: sent / failed / replied / bounced."""
    import csv

    # 1. Parse runs.log for daily aggregates
    daily = {}
    for runs_path in Path("/root/.openclaw/workspace/outreach").glob("user_*/runs.log"):
        try:
            with open(runs_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 2:
                        continue
                    ts_str = parts[0]
                    try:
                        dt = datetime.fromisoformat(ts_str)
                        day = dt.strftime("%Y-%m-%d")
                    except Exception:
                        continue
                    data = {}
                    for p in parts[1:]:
                        if "=" in p:
                            k, v = p.split("=", 1)
                            data[k] = v
                    sent = int(data.get("sent", "0") or "0")
                    failed = int(data.get("failed", "0") or "0")
                    if day not in daily:
                        daily[day] = {"sent": 0, "failed": 0, "replied": 0, "bounced": 0}
                    daily[day]["sent"] += sent
                    daily[day]["failed"] += failed
        except Exception:
            continue

    # 2. Parse sequences.csv for replied / bounced per day
    for seq_path in Path("/root/.openclaw/workspace/outreach").glob("user_*/sequences.csv"):
        try:
            with open(seq_path, "r", encoding="utf-8-sig") as f:
                reader_csv = csv.DictReader(f)
                for row in reader_csv:
                    sent_at = row.get("sent_at", "").strip()
                    status = row.get("status", "").strip()
                    if not sent_at:
                        continue
                    try:
                        dt = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
                        day = dt.strftime("%Y-%m-%d")
                    except Exception:
                        continue
                    if day not in daily:
                        daily[day] = {"sent": 0, "failed": 0, "replied": 0, "bounced": 0}
                    if status == "replied":
                        daily[day]["replied"] += 1
                    elif status == "bounced":
                        daily[day]["bounced"] += 1
        except Exception:
            continue

    # Sort by date descending
    report_rows = sorted(daily.items(), key=lambda x: x[0], reverse=True)

    # Totals
    totals = {"sent": 0, "failed": 0, "replied": 0, "bounced": 0}
    for _, vals in report_rows:
        for k in totals:
            totals[k] += vals[k]

    return templates.TemplateResponse("reports.html", {
        "request": request,
        "report_rows": report_rows,
        "totals": totals,
    })


@app.get("/portal/outreach/wizard", response_class=HTMLResponse)
async def sequence_wizard(request: Request, _: str = Depends(require_auth)):
    files = reader.list_lead_files()
    # Only show files that are not sequences themselves — filter to enriched/verified/leadgen stages
    source_files = [f for f in files if f.stage in ("enriched", "verified", "leadgen") and f.row_count > 0]
    # Also include outreach source lists
    extra_sources = []
    for user_dir in Path("/root/.openclaw/workspace/outreach").glob("user_*"):
        for p in user_dir.glob("source_list*.csv"):
            try:
                count = sum(1 for _ in open(p, encoding="utf-8-sig")) - 1
                extra_sources.append({"path": str(p), "name": p.name, "row_count": count, "label": f"[Outreach source] {p.name} ({count} leads)"})
            except Exception:
                pass
    return templates.TemplateResponse("sequence_wizard.html", {
        "request": request,
        "source_files": source_files,
        "extra_sources": extra_sources,
    })


@app.post("/portal/outreach/wizard/generate")
async def sequence_wizard_generate(
    request: Request,
    input_path: str = Form(...),
    sender_name: str = Form(""),
    campaign_name: str = Form(""),
    allow_personal: str = Form("off"),
    sequence_type: str = Form("multi"),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Validate input path is within allowed dirs
    safe_path = Path(input_path).resolve()
    allowed_roots = [
        Path("/root/.openclaw/workspace/leads").resolve(),
        Path("/root/.openclaw/workspace/outreach").resolve(),
    ]
    if not any(str(safe_path).startswith(str(r)) for r in allowed_roots):
        raise HTTPException(status_code=400, detail="Invalid source path")
    if not safe_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found")

    # Build output path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_campaign = re.sub(r"[^\w\-]", "_", campaign_name.strip() or "sequences")
    out_path = Path("/root/.openclaw/workspace/leads") / f"sequences_{safe_campaign}_{ts}.csv"

    # Build command — never include send flags
    cmd = [
        "python3", str(OUTREACH_SCRIPTS / "generate_sequences.py"),
        str(safe_path),
        "--output", str(out_path),
        "--sender-name", sender_name.strip(),
        "--campaign-name", campaign_name.strip() or "portal-wizard",
    ]
    if sequence_type == "single":
        cmd.append("--single")
    if allow_personal == "on":
        cmd.append("--allow-personal")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            error_msg = (result.stderr or result.stdout or "Unknown error")[:300]
            raise HTTPException(status_code=500, detail=f"Generation failed: {error_msg}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Generation timed out (>2 min). Try a smaller file.")

    row_count = sum(1 for _ in open(out_path, encoding="utf-8-sig")) - 1 if out_path.exists() else 0
    return RedirectResponse(
        f"/portal/outreach?msg=wizard-done&sequences={out_path.name}&count={row_count}",
        status_code=303
    )


@app.get("/portal/imap-settings", response_class=HTMLResponse)
async def imap_settings(request: Request, _: str = Depends(require_auth)):
    accounts = imap_auth.list_accounts()
    return templates.TemplateResponse("imap_settings.html", {
        "request": request,
        "accounts": accounts,
    })


@app.post("/portal/imap-settings/save")
async def imap_settings_save(
    request: Request,
    email_addr: str = Form(...),
    app_password: str = Form(...),
    imap_server: str = Form("imap.gmail.com"),
    imap_port: int = Form(993),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    email_addr = email_addr.strip().lower()
    if not email_addr or "@" not in email_addr:
        raise HTTPException(status_code=400, detail="Invalid email address")
    if not app_password.strip():
        raise HTTPException(status_code=400, detail="App password required")

    imap_auth.save_account(email_addr, app_password.strip(), imap_server, imap_port, configured_by="portal")
    return RedirectResponse("/portal/imap-settings?msg=saved", status_code=303)


@app.post("/portal/imap-settings/test")
async def imap_settings_test(
    request: Request,
    email_addr: str = Form(...),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    ok, msg = imap_auth.test_connection(email_addr.strip().lower())
    status = "ok" if ok else "fail"
    return RedirectResponse(
        f"/portal/imap-settings?msg=test-{status}&detail={quote_plus(msg[:80])}",
        status_code=303
    )


@app.post("/portal/imap-settings/delete")
async def imap_settings_delete(
    request: Request,
    email_addr: str = Form(...),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    imap_auth.delete_account(email_addr.strip().lower())
    return RedirectResponse("/portal/imap-settings?msg=deleted", status_code=303)


@app.get("/portal/deliverability", response_class=HTMLResponse)
async def deliverability(request: Request, _: str = Depends(require_auth)):
    report = reader.get_deliverability_report()
    suppressions = reader.get_suppression_list()
    return templates.TemplateResponse("deliverability.html", {
        "request": request,
        "report": report,
        "suppressions": suppressions,
    })


@app.post("/portal/deliverability/run-check")
async def deliverability_run_check(
    request: Request,
    domain: str = Form(""),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if not domain:
        campaigns = reader.get_active_campaigns()
        for c in campaigns:
            for s in c.senders:
                email = s.get("email", "")
                if "@" in email:
                    domain = email.split("@")[1]
                    break
            if domain:
                break
        if not domain:
            domain = "miraeadvisory.com"

    try:
        raw = _check_domain(domain)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check failed: {e}")

    portal_report: dict = {
        "_domain": domain,
        "_last_checked": datetime.now(timezone.utc).isoformat(),
    }
    for check_name in ("mx", "spf", "dkim", "dmarc"):
        d = raw.get(check_name, {})
        passed = d.get("pass", False)
        notes = d.get("notes", [])
        records_raw = d.get("records", [])
        if check_name == "dkim":
            records_str = [f"{sel}" for sel, _ in records_raw[:3]] if records_raw else []
        else:
            records_str = [str(r)[:80] for r in records_raw[:3]]
        portal_report[check_name] = {
            "status": "ok" if passed else "fail",
            "detail": notes[0] if notes else ("No issues found" if passed else "Check failed — see notes"),
            "notes": notes,
            "records": records_str,
        }

    report_path = Path("/root/.openclaw/workspace/deliverability.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(portal_report, f, indent=2)

    return RedirectResponse("/portal/deliverability?msg=checked", status_code=303)


@app.post("/portal/imap-settings/{email_addr}/run-tracker")
async def imap_run_tracker(
    email_addr: str,
    request: Request,
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    campaigns = reader.get_active_campaigns()
    sequences_csv = None
    for c in campaigns:
        for s in c.senders:
            if s.get("email", "").lower() == email_addr.lower():
                if c.sequences_csv and c.sequences_csv.exists():
                    sequences_csv = str(c.sequences_csv)
                    break
        if sequences_csv:
            break

    if not sequences_csv:
        return RedirectResponse("/portal/imap-settings?msg=tracker-no-campaign", status_code=303)

    try:
        result = subprocess.run(
            ["python3", str(OUTREACH_SCRIPTS / "workspace_imap_tracker.py"),
             "--sequences", sequences_csv,
             "--account-email", email_addr],
            capture_output=True, text=True, timeout=60
        )
        status = "tracker-ok" if result.returncode == 0 else "tracker-fail"
    except subprocess.TimeoutExpired:
        status = "tracker-timeout"

    return RedirectResponse(f"/portal/imap-settings?msg={status}", status_code=303)


@app.get("/portal/master", response_class=HTMLResponse)
async def master(request: Request, _: str = Depends(require_auth)):
    stats = reader.get_master_stats()
    return templates.TemplateResponse("master.html", {
        "request": request,
        "stats": stats,
    })


@app.get("/portal/master/enrich-stream")
async def enrich_stream(_: str = Depends(require_auth)):
    """SSE stream for master enrichment."""
    enrich_script = SKILL_BASE / "sg-enrich" / "scripts" / "enrich_master_free.py"

    async def event_generator():
        if not enrich_script.exists():
            yield f"data: Script not found: {enrich_script}\n\n"
            return

        process = await asyncio.create_subprocess_exec(
            sys.executable, str(enrich_script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                yield f"data: {text}\n\n"
            await process.wait()
            yield f"data: [DONE] Exit code: {process.returncode}\n\n"
        except asyncio.CancelledError:
            process.kill()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/portal/leads/{file_id}/row")
async def edit_row(
    file_id: str,
    row_hash: str = Form(...),
    col: str = Form(...),
    value: str = Form(...),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    lead_file = reader.get_file_by_id(file_id)
    if not lead_file:
        raise HTTPException(status_code=404, detail="File not found")

    ok, err = reader.write_row_edit(lead_file, row_hash, col, value)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "Edit failed")
    return "ok"


@app.post("/portal/leads/{file_id}/delete-rows")
async def delete_rows_post(
    file_id: str,
    row_hashes: str = Form(""),
    csrf: str = Form(""),
    _: str = Depends(require_auth),
):
    if not verify_csrf_token(csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    lead_file = reader.get_file_by_id(file_id)
    if not lead_file:
        raise HTTPException(status_code=404, detail="File not found")

    hashes = [h.strip() for h in row_hashes.split(",") if h.strip()]
    if not hashes:
        raise HTTPException(status_code=400, detail="No rows selected")

    count, err = reader.delete_rows(lead_file, hashes)
    if err:
        raise HTTPException(status_code=500, detail=err)

    return RedirectResponse(f"/portal/leads/{file_id}", status_code=303)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "sg-portal"}


@app.get("/api/v1/stats")
async def stats(_: str = Depends(require_auth)):
    return reader.get_outreach_stats()


@app.get("/api/v1/export/{file_id}")
async def export_csv(
    file_id: str,
    q: str = "",
    sendability: str = "",
    tier: str = "",
    min_score: int = 0,
    has_email: str = "",
    sort_col: str = "",
    sort_dir: str = "asc",
    _: str = Depends(require_auth),
):
    lead_file = reader.get_file_by_id(file_id)
    if not lead_file:
        raise HTTPException(status_code=404, detail="File not found")

    has_email_bool = None
    if has_email == "1":
        has_email_bool = True
    elif has_email == "0":
        has_email_bool = False

    page_data = reader.get_leads_page(
        lead_file,
        q=q,
        sendability=sendability,
        tier=tier,
        min_score=min_score,
        has_email=has_email_bool,
        sort_col=sort_col,
        sort_dir=sort_dir,
        page=1,
        page_size=999_999,  # Export all matching
    )

    output = io.StringIO()
    writer = csv.writer(output)
    if page_data.columns:
        writer.writerow(page_data.columns)
        for row in page_data.rows:
            writer.writerow([reader.formula_inject_protect(row.get(col, "")) for col in page_data.columns])

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="export_{lead_file.filename}"',
        },
    )


@app.get("/portal/logout")
async def logout():
    return Response(
        content="Logged out",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="SG Portal"'},
    )


@app.get("/portal/logged_out", response_class=HTMLResponse)
async def logged_out(request: Request):
    return templates.TemplateResponse("logged_out.html", {"request": request})
