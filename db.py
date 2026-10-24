"""SQLite storage. Everything runs on one event loop thread, so a single
synchronous connection is enough (and every write is a single statement)."""
import json
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    trade TEXT,
    area TEXT,
    telegram_chat_id INTEGER,
    phone TEXT,
    availability_text TEXT,
    availability_json TEXT,
    pricing_text TEXT,
    pricing_json TEXT,
    quoted_separately TEXT,
    transcript TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    client_chat_id INTEGER,
    client_name TEXT,
    client_phone TEXT,
    trade TEXT,
    when_text TEXT,
    when_json TEXT,
    area TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    accepted_business_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    business_id INTEGER NOT NULL,
    price_note TEXT,
    telegram_message_id INTEGER,
    answer TEXT NOT NULL DEFAULT 'waiting',
    answered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_businesses_trade ON businesses(trade, status);
CREATE INDEX IF NOT EXISTS idx_offers_request ON offers(request_id);
"""

JSON_COLUMNS = {"availability_json", "pricing_json", "when_json"}

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, isolation_level=None, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def init_db() -> None:
    conn()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLUMNS & d.keys():
        if d[k]:
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def _encode(values: dict) -> dict:
    return {
        k: json.dumps(v, ensure_ascii=False) if k in JSON_COLUMNS and v is not None and not isinstance(v, str) else v
        for k, v in values.items()
    }


def query(sql: str, params: tuple = ()) -> list[dict]:
    return [_row(r) for r in conn().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    return _row(conn().execute(sql, params).fetchone())


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    return conn().execute(sql, params)


def insert(table: str, values: dict) -> int:
    values = _encode(values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values())).lastrowid


def update(table: str, row_id: int, values: dict) -> None:
    values = _encode(values)
    sets = ", ".join(f"{k} = ?" for k in values)
    execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))


# --- businesses -------------------------------------------------------------

PROFILE_FIELDS = (
    "name", "trade", "area", "availability_text", "availability_json",
    "pricing_text", "pricing_json", "quoted_separately",
)


def get_business(business_id: int) -> dict | None:
    return query_one("SELECT * FROM businesses WHERE id = ?", (business_id,))


def get_business_by_chat(chat_id: int) -> dict | None:
    return query_one(
        "SELECT * FROM businesses WHERE telegram_chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,)
    )


def save_business(chat_id: int, profile: dict, status: str, phone: str | None = None,
                  transcript: str | None = None) -> int:
    """Create or update the business for this chat with the given profile fields."""
    values = {k: profile.get(k) for k in PROFILE_FIELDS}
    values["status"] = status
    values["updated_at"] = utcnow()
    if phone:
        values["phone"] = phone
    if transcript:
        values["transcript"] = transcript
    existing = get_business_by_chat(chat_id)
    if existing:
        if transcript and existing.get("transcript"):
            values["transcript"] = existing["transcript"] + "\n---\n" + transcript
        update("businesses", existing["id"], values)
        return existing["id"]
    values["telegram_chat_id"] = chat_id
    values["created_at"] = values["updated_at"]
    return insert("businesses", values)


def active_businesses_for_trade(trade: str) -> list[dict]:
    return query("SELECT * FROM businesses WHERE status = 'active' AND trade = ? ORDER BY id", (trade,))


# --- requests & offers --------------------------------------------------------

def get_request(request_id: int) -> dict | None:
    return query_one("SELECT * FROM requests WHERE id = ?", (request_id,))


def get_offer(offer_id: int) -> dict | None:
    return query_one("SELECT * FROM offers WHERE id = ?", (offer_id,))


def offers_for_request(request_id: int) -> list[dict]:
    return query("SELECT * FROM offers WHERE request_id = ? ORDER BY id", (request_id,))
