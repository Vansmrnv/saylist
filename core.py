"""Business logic shared by the MCP server and the business bot."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import db
import llm

log = logging.getLogger("core")

business_bot: Bot | None = None


def init(bot: Bot | None) -> None:
    global business_bot
    business_bot = bot


# --- telegram helpers (never raise: seed data uses fake chat ids) ---------------

async def _send(chat_id, text: str, markup=None) -> int | None:
    if business_bot is None or not chat_id:
        log.warning("not sending to chat %s (no bot or chat id): %s", chat_id, text.splitlines()[0])
        return None
    try:
        msg = await business_bot.send_message(chat_id, text, reply_markup=markup)
        return msg.message_id
    except Exception as e:
        log.warning("could not send to chat %s: %s", chat_id, e)
        return None


async def _edit_offer(offer: dict, request: dict, status_line: str) -> None:
    """Rewrite an offer message with a status line and no buttons."""
    business = db.get_business(offer["business_id"])
    if business_bot is None or not business or not offer.get("telegram_message_id"):
        log.warning("not editing offer %s: %s", offer["id"], status_line)
        return
    try:
        await business_bot.edit_message_text(
            text=f"{job_text(request, offer['price_note'])}\n\n{status_line}",
            chat_id=business["telegram_chat_id"],
            message_id=offer["telegram_message_id"],
            reply_markup=None,
        )
    except Exception as e:
        log.warning("could not edit offer %s: %s", offer["id"], e)


def job_text(request: dict, price_note: str | None) -> str:
    lines = [
        f"🛠 <b>New job: {escape(trade_label(request['trade']))}</b>",
        f"🕒 When: {escape(request.get('when_text') or '-')}",
        f"📍 Area: {escape(request.get('area') or '-')}",
        f"📝 Details: {escape(request.get('description') or '-')}",
        f"💶 Your price: {escape(price_note or '-')}",
    ]
    return "\n".join(lines)


def offer_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Accept", callback_data=f"accept:{offer_id}"),
        InlineKeyboardButton(text="❌ Decline", callback_data=f"decline:{offer_id}"),
    ]])


def trade_label(trade: str | None) -> str:
    return "AC technician" if trade == "ac_technician" else (trade or "other").capitalize()


def _set_offer(offer_id: int, answer: str) -> None:
    db.update("offers", offer_id, {"answer": answer, "answered_at": db.utcnow()})


# --- requests ----------------------------------------------------------------------

async def create_and_dispatch(channel: str, client_name: str | None, client_phone: str | None,
                              request: dict, client_chat_id: int | None = None) -> dict:
    """Save a request, find available businesses and send each one an offer.
    `request` has trade, when_text, when_json, area, description."""
    request_id = db.insert("requests", {
        "channel": channel,
        "client_chat_id": client_chat_id,
        "client_name": client_name,
        "client_phone": client_phone,
        "trade": request["trade"],
        "when_text": request.get("when_text"),
        "when_json": request.get("when_json"),
        "area": request.get("area"),
        "description": request.get("description"),
        "status": "open",
        "created_at": db.utcnow(),
    })
    saved = db.get_request(request_id)
    candidates = db.active_businesses_for_trade(request["trade"])
    try:
        matches = await llm.match_businesses(request, candidates)
    except Exception:
        db.update("requests", request_id, {"status": "no_match"})
        raise
    by_id = {b["id"]: b for b in candidates}
    available = [m for m in matches if m.available]
    log.info("request %s: %d candidates, %d available", request_id, len(candidates), len(available))

    for m in available:
        business = by_id[m.business_id]
        offer_id = db.insert("offers", {
            "request_id": request_id, "business_id": business["id"],
            "price_note": m.price_note, "answer": "waiting",
        })
        message_id = await _send(business["telegram_chat_id"], job_text(saved, m.price_note), offer_keyboard(offer_id))
        if message_id:
            db.update("offers", offer_id, {"telegram_message_id": message_id})

    if not available:
        db.update("requests", request_id, {"status": "no_match"})
    return {"request_id": request_id, "sent_to": len(available), "status": "open" if available else "no_match"}


CLOSED_REPLIES = {
    "accepted": "You already accepted this job.",
    "declined": "You declined this job.",
    "too_late": "Sorry, this job was already taken.",
    "expired": "This request has expired.",
}


async def accept(offer_id: int) -> str:
    """Business tapped Accept. Returns a short text for the button toast."""
    offer = db.get_offer(offer_id)
    if not offer:
        return "Offer not found."
    if offer["answer"] != "waiting":
        return CLOSED_REPLIES[offer["answer"]]
    request = db.get_request(offer["request_id"])

    claimed = db.execute(
        "UPDATE requests SET status = 'accepted', accepted_business_id = ? WHERE id = ? AND status = 'open'",
        (offer["business_id"], request["id"]),
    ).rowcount
    if claimed == 0:
        _set_offer(offer_id, "too_late")
        await _edit_offer(offer, request, "😔 Sorry, this job was already taken.")
        return "Sorry, this job was already taken."

    _set_offer(offer_id, "accepted")
    business = db.get_business(offer["business_id"])
    log.info("request %s accepted by business %s (%s)", request["id"], business["id"], business["name"])
    await _edit_offer(offer, request, "✅ <b>You accepted this job.</b>")
    await _send(business["telegram_chat_id"], "\n".join([
        "🎉 <b>The job is yours!</b> Please contact the client:",
        f"👤 {escape(request.get('client_name') or '-')}",
        f"📞 {escape(request.get('client_phone') or '-')}",
        f"📍 {escape(request.get('area') or '-')}",
        f"🕒 {escape(request.get('when_text') or '-')}",
        f"📝 {escape(request.get('description') or '-')}",
    ]))

    for other in db.offers_for_request(request["id"]):
        if other["id"] != offer_id and other["answer"] == "waiting":
            _set_offer(other["id"], "too_late")
            await _edit_offer(other, request, "🔒 This job was taken by someone else.")
    return "You got the job!"


async def decline(offer_id: int) -> str:
    offer = db.get_offer(offer_id)
    if not offer:
        return "Offer not found."
    if offer["answer"] != "waiting":
        return CLOSED_REPLIES[offer["answer"]]
    request = db.get_request(offer["request_id"])
    _set_offer(offer_id, "declined")
    await _edit_offer(offer, request, "❌ Declined.")

    answers = {o["answer"] for o in db.offers_for_request(request["id"])}
    if answers == {"declined"}:
        db.execute("UPDATE requests SET status = 'no_match' WHERE id = ? AND status = 'open'", (request["id"],))
        log.info("request %s: every business declined", request["id"])
    return "Declined."


def get_status(request_id: int) -> dict | None:
    request = db.get_request(request_id)
    if not request:
        return None
    offers = db.offers_for_request(request_id)
    result = {
        "request_id": request_id,
        "status": request["status"],
        "trade": request["trade"],
        "when": request["when_text"],
        "area": request["area"],
        "sent_to": len(offers),
        "declined": sum(o["answer"] == "declined" for o in offers),
        "waiting": sum(o["answer"] == "waiting" for o in offers),
    }
    if request["status"] == "accepted":
        business = db.get_business(request["accepted_business_id"])
        offer = next((o for o in offers if o["answer"] == "accepted"), {})
        result.update({
            "business_name": business["name"],
            "business_phone": business["phone"],
            "price_note": offer.get("price_note"),
            "quoted_separately": business.get("quoted_separately"),
        })
    return result


# --- expiry ------------------------------------------------------------------------

async def expire_old_requests() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config.REQUEST_TIMEOUT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    for request in db.query("SELECT * FROM requests WHERE status = 'open' AND created_at < ?", (cutoff,)):
        expired = db.execute(
            "UPDATE requests SET status = 'expired' WHERE id = ? AND status = 'open'", (request["id"],)
        ).rowcount
        if not expired:
            continue
        log.info("request %s expired", request["id"])
        for offer in db.offers_for_request(request["id"]):
            if offer["answer"] == "waiting":
                _set_offer(offer["id"], "expired")
                await _edit_offer(offer, request, "⌛ This request expired.")


async def expiry_loop() -> None:
    while True:
        try:
            await expire_old_requests()
        except Exception:
            log.exception("expiry loop error")
        await asyncio.sleep(30)
