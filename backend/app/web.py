"""HTML pages: the customer's live tracking page (/t/<token>) and the demo admin page (/admin)."""

from datetime import datetime
from html import escape
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings, now_local
from app.core.db import get_session
from app.modules import businesses, jobs, messaging

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]

BASE_CSS = """
:root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#667085; --line:#e4e7ec;
  --ok:#12b76a; --okbg:#ecfdf3; --warn:#b54708; --warnbg:#fffaeb; --off:#98a2b3; --offbg:#f2f4f7;
  --accent:#2e6be6; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f1115; --card:#181b21; --ink:#e7e9ee;
  --muted:#98a2b3; --line:#2a2f38; --okbg:#0c2b1e; --warnbg:#2e2208; --offbg:#22262e; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.45 -apple-system, system-ui, "Segoe UI", Roboto, sans-serif; }
.pill { display:inline-block; padding:1px 9px; border-radius:999px; font-size:12px;
  font-weight:600; }
.ok { background:var(--okbg); color:var(--ok); }
.warn { background:var(--warnbg); color:var(--warn); }
.off { background:var(--offbg); color:var(--off); }
"""

PILL = {
    "active": "ok", "booked": "ok", "on_the_way": "ok", "arrived": "ok", "done": "ok",
    "accepted": "ok", "sent": "ok", "draft": "warn", "open": "warn", "waiting": "warn",
    "pending": "warn", "proposed": "warn",
}  # fmt: skip


def _pill(value: Any) -> str:
    text = str(value)
    return f'<span class="pill {PILL.get(text, "off")}">{escape(text.replace("_", " "))}</span>'


def _t(at: datetime | None, fmt: str = "%d %b %H:%M:%S") -> str:
    return at.astimezone(get_settings().tz).strftime(fmt) if at else ""


# --- tracking page --------------------------------------------------------------------------

TRACK_CSS = """
main { max-width:520px; margin:0 auto; padding:20px 16px 40px; }
.brand { color:var(--muted); font-size:13px; letter-spacing:.04em; text-transform:uppercase; }
.status { font-size:24px; font-weight:700; margin:6px 0 18px; line-height:1.25; }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px;
  margin-bottom:14px; }
.steps { display:flex; justify-content:space-between; margin:0 0 18px; padding:0; list-style:none; }
.steps li { flex:1; text-align:center; font-size:12px; color:var(--muted); position:relative; }
.steps li::before { content:""; display:block; width:14px; height:14px; margin:0 auto 6px;
  border-radius:50%; background:var(--line); }
.steps li.done { color:var(--ink); } .steps li.done::before { background:var(--ok); }
.steps li.now::before { box-shadow:0 0 0 5px var(--okbg); }
.row { display:flex; gap:10px; margin:6px 0; } .row b { min-width:84px; color:var(--muted);
  font-weight:500; }
.timeline { list-style:none; margin:0; padding:0; } .timeline li { padding:6px 0;
  border-top:1px solid var(--line); display:flex; gap:12px; }
.timeline li:first-child { border-top:0; } .timeline time { color:var(--muted); min-width:44px; }
button.big { width:100%; padding:16px; font-size:18px; font-weight:700; border:0;
  border-radius:12px; background:var(--ok); color:#fff; }
a { color:var(--accent); } .small { font-size:13px; color:var(--muted); }
"""

STEPS = [
    ("Requested", {jobs.JobStatus.DRAFT, jobs.JobStatus.OPEN}),
    ("Booked", {jobs.JobStatus.BOOKED}),
    ("On the way", {jobs.JobStatus.ON_THE_WAY}),
    ("At the door", {jobs.JobStatus.ARRIVED}),
    ("Done", {jobs.JobStatus.DONE}),
]


def _steps(status: jobs.JobStatus) -> str:
    current = next((i for i, (_, statuses) in enumerate(STEPS) if status in statuses), None)
    items = []
    for i, (label, _) in enumerate(STEPS):
        css = "done" if current is not None and i <= current else ""
        css += " now" if i == current else ""
        items.append(f'<li class="{css}">{label}</li>')
    return f'<ol class="steps">{"".join(items)}</ol>'


FINAL = (
    jobs.JobStatus.DONE,
    jobs.JobStatus.CANCELLED,
    jobs.JobStatus.EXPIRED,
    jobs.JobStatus.NO_MATCH,
)


def render_tracking(job: jobs.JobView) -> str:
    live = job.status not in FINAL
    coming = any(e.kind == jobs.EventKind.CUSTOMER_COMING for e in job.timeline)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<meta http-equiv='refresh' content='4'>" if live else "",
        f"<title>Your {escape(job.trade)}</title><style>{BASE_CSS}{TRACK_CSS}</style></head>",
        "<body><main>",
        f"<div class='brand'>saylist · job #{job.job_id}</div>",
        f"<div class='status'>{escape(job.status_text)}</div>",
        _steps(job.status),
    ]
    if job.status == jobs.JobStatus.ARRIVED:
        if coming:
            parts.append("<div class='card'><b>👋 They know you're coming.</b></div>")
        else:
            parts.append(
                f"<form method='post' action='/t/{escape(job.token)}/coming' class='card'>"
                "<button class='big'>👋 I'm coming to the door</button></form>"
            )
    if job.business_name:
        when = (
            f"ETA {_t(job.eta_at, '%H:%M')}"
            if job.status == jobs.JobStatus.ON_THE_WAY and job.eta_at
            else _t(job.scheduled_for, "%a %d %b, %H:%M")
        )
        phone = escape(job.business_phone or "")
        parts.append(
            "<div class='card'>"
            f"<div class='row'><b>Who</b><span>{escape(job.business_name)}</span></div>"
            f"<div class='row'><b>When</b><span>{escape(when)}</span></div>"
            f"<div class='row'><b>Price</b><span>{escape(job.price_note or '-')}</span></div>"
            f"<div class='small'>No need to call. Only if something goes wrong: "
            f"<a href='tel:{phone}'>{phone}</a></div></div>"
        )
    parts.append(
        "<div class='card'>"
        f"<div class='row'><b>Job</b><span>{escape(job.description)}</span></div>"
        f"<div class='row'><b>Address</b><span>{escape(job.address)}</span></div>"
        f"<div class='row'><b>Getting in</b><span>{escape(job.access_notes)}</span></div>"
        f"<div class='row'><b>Asked for</b><span>{escape(job.when)}</span></div></div>"
    )
    events = "".join(
        f"<li><time>{_t(e.at, '%H:%M')}</time><span>{escape(e.text)}</span></li>"
        for e in reversed(job.timeline)
    )
    parts.append(f"<div class='card'><ul class='timeline'>{events}</ul></div>")
    if live:
        parts.append("<div class='small'>This page updates by itself.</div>")
    parts.append("</main></body></html>")
    return "".join(parts)


@router.get("/t/{token}", response_class=HTMLResponse)
async def tracking_page(token: str, session: Session) -> str:
    job = await jobs.get_by_token(session, token)
    if job is None:
        raise HTTPException(404, "Unknown tracking link")
    return render_tracking(job)


@router.post("/t/{token}/coming")
async def tracking_coming(token: str, session: Session) -> RedirectResponse:
    await jobs.customer_coming(session, token)
    return RedirectResponse(f"/t/{token}", status_code=303)


# --- admin page -------------------------------------------------------------------------------

ADMIN_CSS = """
body { padding:24px; } h1 { font-size:22px; margin:0 0 4px; } .sub { color:var(--muted); }
h2 { font-size:16px; margin:26px 0 8px; }
table { border-collapse:collapse; width:100%; background:var(--card);
  border:1px solid var(--line); }
th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line);
  vertical-align:top; }
th { font-weight:600; white-space:nowrap; color:var(--muted); } td.empty { text-align:center;
  color:var(--muted); padding:16px; } a { color:var(--accent); }
"""


def _table(title: str, headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    if not rows:
        body = f"<tr><td class='empty' colspan='{len(headers)}'>Nothing yet</td></tr>"
    return f"<h2>{escape(title)} ({len(rows)})</h2><table><tr>{head}</tr>{body}</table>"


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(session: Session) -> str:
    e = escape
    biz = await businesses.list_all(session)
    job_views = await jobs.list_recent(session)
    offers = await jobs.list_recent_offers(session)
    outbox = await messaging.list_recent(session, limit=25)
    names = {b.id: b.name or f"#{b.id}" for b in biz}
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><meta http-equiv='refresh' content='3'>",
        f"<title>Admin</title><style>{BASE_CSS}{ADMIN_CSS}</style></head><body>",
        "<h1>Live dashboard</h1>",
        f"<div class='sub'>Refreshes every 3 s · {e(get_settings().timezone)} · "
        f"{now_local():%H:%M:%S}</div>",
        _table(
            "Jobs",
            ["id", "status", "now", "trade", "address", "access", "customer", "business", "track"],
            [
                [
                    str(j.job_id),
                    _pill(j.status),
                    e(j.status_text),
                    e(j.trade),
                    e(j.address),
                    e(j.access_notes),
                    e(j.customer_name),
                    e(j.business_name or ""),
                    f"<a href='/t/{e(j.token)}' target='_blank'>open</a>",
                ]
                for j in job_views
            ],
        ),
        _table(
            "Offers",
            ["id", "job", "business", "answer", "price", "times offered", "answered"],
            [
                [
                    str(o.id),
                    str(o.job_id),
                    e(names.get(o.business_id, str(o.business_id))),
                    _pill(o.answer),
                    e(o.price_note or ""),
                    e(" · ".join(o.options)),
                    _t(o.answered_at),
                ]
                for o in offers
            ],
        ),
        _table(
            "Businesses",
            ["id", "status", "name", "trade", "area", "phone", "availability", "prices", "chat"],
            [
                [
                    str(b.id),
                    _pill(b.status),
                    e(b.name or ""),
                    e(b.trade or ""),
                    e(b.area or ""),
                    e(b.phone or ""),
                    e(b.availability_text or ""),
                    e(b.pricing_text or ""),
                    str(b.telegram_chat_id),
                ]
                for b in biz
            ],
        ),
        _table(
            "Outbox (Telegram delivery)",
            ["id", "key", "kind", "to", "status", "tries", "error", "sent"],
            [
                [
                    str(m.id),
                    e(m.key),
                    e(m.kind),
                    str(m.chat_id),
                    _pill(m.status),
                    str(m.attempts),
                    e((m.last_error or "")[:60]),
                    _t(m.sent_at),
                ]
                for m in outbox
            ],
        ),
        "</body></html>",
    ]
    return "".join(parts)


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/admin")
