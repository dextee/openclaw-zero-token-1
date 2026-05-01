from pathlib import Path
import asyncio, csv, hashlib, io, json, os, re, subprocess, sys
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import reader
from auth import get_csrf_token, require_auth, verify_csrf_token

PORTAL_DIR = Path(__file__).parent
TEMPLATES_DIR = PORTAL_DIR / "templates"

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
    return templates.TemplateResponse(
        "500.html",
        {"request": request, "detail": str(exc)},
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
    stage_map = {"leadgen": "sg-leadgen", "enriched": "sg-enrich", "verified": "sg-verify"}
    dest_dir = SKILL_BASE / stage_map[stage] / "leads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    # Path jail
    resolved = dest_path.resolve()
    if not str(resolved).startswith(str(SKILL_BASE.resolve())):
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
async def campaigns_list(request: Request, _: str = Depends(require_auth)):
    campaigns = reader.list_campaigns()
    return templates.TemplateResponse("campaigns.html", {
        "request": request,
        "campaigns": campaigns,
    })


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


@app.get("/portal/deliverability", response_class=HTMLResponse)
async def deliverability(request: Request, _: str = Depends(require_auth)):
    report = reader.get_deliverability_report()
    suppressions = reader.get_suppression_list()
    return templates.TemplateResponse("deliverability.html", {
        "request": request,
        "report": report,
        "suppressions": suppressions,
    })


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
