import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BUSINESS_BOT_TOKEN = os.getenv("BUSINESS_BOT_TOKEN", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or "claude-sonnet-5-5"
LLM_EFFORT = os.getenv("LLM_EFFORT", "").strip() or "low"
TIMEZONE = os.getenv("TIMEZONE", "").strip() or "Asia/Nicosia"
REQUEST_TIMEOUT_MINUTES = float(os.getenv("REQUEST_TIMEOUT_MINUTES", "") or 10)
PORT = int(os.getenv("PORT", "") or 8000)
DB_PATH = os.getenv("DB_PATH", "").strip() or "app.db"

TZ = ZoneInfo(TIMEZONE)

TRADES = ["electrician", "plumber", "locksmith", "handyman", "cleaner", "ac_technician", "other"]


def now_local() -> datetime:
    return datetime.now(TZ)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# aiogram logs every update at INFO; keep the console readable for the demo
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
