"""What the business sees in Telegram: the offer, then the job card that follows the job's status.
Text is HTML (the bot's parse mode); every customer-supplied value is escaped."""

from datetime import datetime
from html import escape

from app.core.config import get_settings
from app.modules.businesses import trade_label
from app.modules.jobs._models import Job, JobOffer
from app.modules.jobs._schemas import ArrivalOption, BusinessAction, JobStatus
from app.modules.messaging import Button

ETA_CHOICES = (10, 20, 40)


def offer_key(offer_id: int) -> str:
    return f"job_offer:{offer_id}"


def _local(at: datetime) -> datetime:
    return at.astimezone(get_settings().tz)


def _when_line(job: Job) -> str:
    if job.status == JobStatus.ON_THE_WAY and job.eta_at:
        return f"🚗 On the way · ETA {_local(job.eta_at):%H:%M}"
    if job.scheduled_for:
        return f"🗓 Booked: {_local(job.scheduled_for):%a %d %b, %H:%M}"
    return f"🕒 Customer wants: {escape(job.when_text)}"


OFFER_FOOTER = "<b>Tap a time to take the job.</b> First tap wins; the customer is told instantly."


def offer_text(job: Job, offer: JobOffer, footer: str = OFFER_FOOTER) -> str:
    return "\n".join(
        [
            f"🛠 <b>New job: {escape(trade_label(job.trade))}</b>",
            f"📝 {escape(job.description)}",
            f"🕒 Customer wants: {escape(job.when_text)}",
            f"📍 {escape(job.street_address)}, {escape(job.city)}",
            f"💶 Your price: {escape(offer.price_note or '-')}",
            "",
            footer,
        ]
    )


def offer_buttons(offer: JobOffer) -> list[list[Button]]:
    options = [ArrivalOption.model_validate(o) for o in offer.options]
    rows = [
        [Button(text=f"✅ {o.label}", callback_data=f"acc:{offer.id}:{i}")]
        for i, o in enumerate(options)
    ]
    rows.append([Button(text="❌ Decline", callback_data=f"dec:{offer.id}")])
    return rows


STATUS_LINES = {
    JobStatus.BOOKED: "Tap 🚗 when you leave. The customer follows your status live.",
    JobStatus.ON_THE_WAY: "Tap 📍 when you're at the door. The customer is told to let you in.",
    JobStatus.ARRIVED: "The customer knows you're here. Tap ✅ when the job is done.",
    JobStatus.DONE: "✅ <b>Job done.</b> Thank you!",
    JobStatus.CANCELLED: "❌ <b>This job was cancelled.</b>",
}


def job_card_text(job: Job, offer: JobOffer, extra: str | None = None) -> str:
    lines = [
        f"<b>{escape(trade_label(job.trade))} job #{job.id}</b>",
        _when_line(job),
        f"📝 {escape(job.description)}",
        f"📍 <b>{escape(job.street_address)}, {escape(job.city)}</b>",
        f"🏢 {escape(job.unit)}",
        f"🔑 {escape(job.access_notes)}",
        f"👤 {escape(job.customer_name)}",
        f"💶 {escape(offer.price_note or '-')}",
        f"📞 {escape(job.customer_phone)} <i>(only if you can't get in)</i>",
        "",
        STATUS_LINES.get(job.status, ""),
    ]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def job_card_buttons(job: Job) -> list[list[Button]]:
    maps = [Button(text="🗺 Open in Maps", url=job.maps_url)]
    act = f"job:{job.id}"
    cancel = [Button(text="Can't make it", callback_data=f"{act}:{BusinessAction.CANCEL}")]
    if job.status == JobStatus.BOOKED:
        eta = [
            Button(
                text=f"🚗 On my way · {m} min",
                callback_data=f"{act}:{BusinessAction.ON_THE_WAY}:{m}",
            )
            for m in ETA_CHOICES
        ]
        return [maps, eta[:2], eta[2:], cancel]
    if job.status == JobStatus.ON_THE_WAY:
        here = [Button(text="📍 I'm at the door", callback_data=f"{act}:{BusinessAction.ARRIVED}")]
        return [maps, here, cancel]
    if job.status == JobStatus.ARRIVED:
        return [[Button(text="✅ Job done", callback_data=f"{act}:{BusinessAction.DONE}")]]
    return []
