"""GET /admin: live view of the three tables for the demo screen."""
import json
from datetime import datetime, timezone
from html import escape

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

import config
import db

TABLES = {
    "Businesses": ("businesses", ["id", "status", "name", "trade", "area", "phone", "availability_text",
                                  "pricing_text", "quoted_separately", "telegram_chat_id", "updated_at"]),
    "Requests": ("requests", ["id", "status", "channel", "trade", "when_text", "area", "description",
                              "client_name", "client_phone", "accepted_business_id", "created_at"]),
    "Offers": ("offers", ["id", "request_id", "business_id", "answer", "price_note", "answered_at"]),
}

STYLE = """
body { font: 14px/1.4 -apple-system, system-ui, Segoe UI, Roboto, sans-serif; margin: 24px; color: #1f2328; background: #f6f8fa; }
h1 { font-size: 22px; margin: 0 0 4px; } .sub { color: #656d76; margin-bottom: 20px; }
h2 { font-size: 16px; margin: 24px 0 8px; }
table { border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #d0d7de; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eaeef2; vertical-align: top; }
th { background: #f6f8fa; font-weight: 600; white-space: nowrap; }
td.empty { color: #8c959f; text-align: center; padding: 16px; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }
.active, .accepted { background: #dafbe1; color: #116329; }
.open, .waiting, .draft { background: #fff8c5; color: #7d4e00; }
.declined, .too_late, .expired, .no_match { background: #eaeef2; color: #57606a; }
"""

STATUS_COLUMNS = {"status", "answer"}


def _local(ts: str | None) -> str:
    if not ts:
        return ""
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(config.TZ).strftime("%d %b %H:%M:%S")


def _cell(col: str, value) -> str:
    if value is None:
        return ""
    if col in STATUS_COLUMNS:
        return f'<span class="pill {escape(str(value))}">{escape(str(value))}</span>'
    if col.endswith("_at"):
        return escape(_local(value))
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return escape(value)


def render() -> str:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><meta http-equiv='refresh' content='3'>",
        f"<title>Admin</title><style>{STYLE}</style></head><body>",
        "<h1>Live dashboard</h1>",
        f"<div class='sub'>Auto-refreshes every 3 seconds · times in {escape(config.TIMEZONE)} · "
        f"{config.now_local():%H:%M:%S}</div>",
    ]
    for title, (table, cols) in TABLES.items():
        rows = db.query(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 100")
        parts.append(f"<h2>{title} ({len(rows)})</h2><table><tr>")
        parts.extend(f"<th>{escape(c.replace('_', ' '))}</th>" for c in cols)
        parts.append("</tr>")
        if not rows:
            parts.append(f"<tr><td class='empty' colspan='{len(cols)}'>Nothing yet</td></tr>")
        for r in rows:
            parts.append("<tr>" + "".join(f"<td>{_cell(c, r.get(c))}</td>" for c in cols) + "</tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)


def register(mcp) -> None:
    @mcp.custom_route("/admin", methods=["GET"])
    async def admin_page(request: Request):
        return HTMLResponse(render())

    @mcp.custom_route("/", methods=["GET"])
    async def root(request: Request):
        return RedirectResponse("/admin")
