from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.businesses import Availability, TimeSlot
from app.modules.jobs import When, arrival_options

TZ = ZoneInfo("Asia/Nicosia")
SATURDAY_NOON = datetime(2026, 10, 24, 12, 0, tzinfo=TZ)
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
AFTER_4PM = When(
    asap=False,
    days_of_week=WEEKDAYS,
    dates=["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"],
    start_time="16:00",
    end_time="24:00",
)
ALWAYS = Availability(always_available=True)


def test_24_7_business_gets_the_start_of_the_window_on_the_first_three_days() -> None:
    options = arrival_options(AFTER_4PM, ALWAYS, SATURDAY_NOON)
    assert [o.label for o in options] == [
        "Mon 26 Oct 16:00",
        "Tue 27 Oct 16:00",
        "Wed 28 Oct 16:00",
    ]


def test_evening_business_starts_when_its_hours_start() -> None:
    evenings = Availability(
        always_available=False,
        slots=[TimeSlot(days=WEEKDAYS, start="17:00", end="23:00")],
    )
    assert arrival_options(AFTER_4PM, evenings, SATURDAY_NOON)[0].label == "Mon 26 Oct 17:00"


def test_no_overlap_means_no_offer() -> None:
    mornings = Availability(
        always_available=False,
        slots=[TimeSlot(days=WEEKDAYS, start="08:00", end="15:00")],
    )
    assert arrival_options(AFTER_4PM, mornings, SATURDAY_NOON) == []


def test_today_starts_at_least_an_hour_from_now_rounded_up() -> None:
    today = When(asap=False, days_of_week=["sat"], dates=["2026-10-24"], start_time="08:00",
                 end_time="20:00")  # fmt: skip
    now = datetime(2026, 10, 24, 12, 20, tzinfo=TZ)
    assert [o.label for o in arrival_options(today, ALWAYS, now)] == ["Today 14:00"]


def test_dates_fall_back_to_days_of_week() -> None:
    monday_only = When(asap=False, days_of_week=["mon"], dates=[], start_time="09:00",
                       end_time="12:00")  # fmt: skip
    assert [o.label for o in arrival_options(monday_only, ALWAYS, SATURDAY_NOON)] == [
        "Mon 26 Oct 09:00"
    ]


def test_asap_offers_minutes_only_when_open_now() -> None:
    asap = When(asap=True, days_of_week=["sat"], dates=["2026-10-24"], start_time=None,
                end_time=None)  # fmt: skip
    assert [o.minutes for o in arrival_options(asap, ALWAYS, SATURDAY_NOON)] == [30, 60]
    weekdays_only = Availability(
        always_available=False,
        slots=[TimeSlot(days=WEEKDAYS, start="08:00", end="18:00")],
    )
    assert arrival_options(asap, weekdays_only, SATURDAY_NOON) == []
