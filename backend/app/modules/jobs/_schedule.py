"""Arrival options: concrete times a business can commit to, from the customer's window and the
business's hours. Pure functions, so the times on the buttons are never an LLM guess."""

from datetime import date, datetime, time, timedelta

from app.modules.businesses import Availability
from app.modules.jobs._schemas import ArrivalOption, When

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_OPTIONS = 3
ASAP_MINUTES = (30, 60)
LEAD_MINUTES = 60  # earliest booking today: an hour from now
DEFAULT_WINDOW = ("08:00", "20:00")


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _windows(availability: Availability, day: date) -> list[tuple[int, int]]:
    if availability.always_available:
        return [(0, 24 * 60)]
    name = DAYS[day.weekday()]
    windows = []
    for slot in availability.slots:
        if name in slot.days:
            start, end = _minutes(slot.start), _minutes(slot.end)
            windows.append((start, end if end > start else 24 * 60))
    return windows


def _dates(when: When, today: date) -> list[date]:
    dates = set()
    for text in when.dates:
        try:
            dates.add(date.fromisoformat(text))
        except ValueError:
            continue
    if not dates:
        dates = {
            today + timedelta(days=i)
            for i in range(7)
            if DAYS[(today + timedelta(days=i)).weekday()] in when.days_of_week
        }
    return sorted(d for d in dates if d >= today)


def label(at: datetime, now: datetime) -> str:
    if at.date() == now.date():
        day = "Today"
    elif at.date() == now.date() + timedelta(days=1):
        day = "Tomorrow"
    else:
        day = at.strftime("%a %d %b")
    return f"{day} {at:%H:%M}"


def arrival_options(when: When, availability: Availability, now: datetime) -> list[ArrivalOption]:
    """Up to three times, earliest first, one per day. Empty: the business is not free then.
    `now` must be timezone-aware local time; returned times are in the same zone."""
    today = now.date()
    now_minutes = now.hour * 60 + now.minute
    if when.asap:
        free_now = any(s <= now_minutes < e for s, e in _windows(availability, today))
        if not free_now:
            return []
        return [
            ArrivalOption(label=f"In {m} min" if m < 60 else f"In {m // 60} h", minutes=m)
            for m in ASAP_MINUTES
        ]

    start = _minutes(when.start_time or DEFAULT_WINDOW[0])
    end = _minutes(when.end_time or DEFAULT_WINDOW[1])
    if end <= start:
        end = 24 * 60
    options: list[ArrivalOption] = []
    for day in _dates(when, today):
        earliest = None
        for b_start, b_end in _windows(availability, day):
            s, e = max(start, b_start), min(end, b_end)
            if day == today:
                s = max(s, now_minutes + LEAD_MINUTES)
            s = -(-s // 60) * 60  # round up to the hour
            if s < e and s < 24 * 60 and (earliest is None or s < earliest):
                earliest = s
        if earliest is not None:
            at = datetime.combine(day, time(earliest // 60, earliest % 60), tzinfo=now.tzinfo)
            options.append(ArrivalOption(label=label(at, now), at=at))
        if len(options) == MAX_OPTIONS:
            break
    return options
