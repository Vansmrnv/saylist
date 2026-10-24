"""The fixed replies: cards, confirmation outcomes, the welcome. Channel-neutral plain text."""

from app.modules import businesses
from app.modules.assistant._schemas import CardField, Choice, Reply, ReplyKind

# Choice values. The seller's tap comes back as one of these (ADR 0003: the only way to confirm).
CONFIRM = "confirm"
CHANGE = "change"
PHONE = "phone"
PHONE_NO = "phone:no"

LANGUAGE = "lang"  # choice value "lang:<code>"

# Asked first, so the welcome arrives in the seller's language. The model writes the welcome;
# after that it follows whatever language the seller writes in.
LANGUAGE_PROMPT = "🌐 Choose a language"
LANGUAGES = {"en": "🇬🇧 English", "ru": "🇷🇺 Русский", "el": "🇬🇷 Ελληνικά"}

# What the welcome must say; the model writes it in the chosen language.
WELCOME_BRIEF = (
    "Write the seller a short welcome. Say that you will bring them jobs from local customers "
    "with the exact address, a booked time and how to get in, so they don't have to call anyone. "
    "Ask them to send a voice note or text saying what they do and their business name, the area "
    "they cover, when they are available and what they charge, and to share their phone number. "
    "Use a short bullet list for the four things."
)
# Used only if the model call fails.
WELCOME = (
    "👋 Hi! I'll bring you jobs from local customers, with the exact address, a booked time "
    "and how to get in, so you don't have to call anyone.\n\n"
    "Send me a voice note (or text) saying:\n"
    "• what you do and your business name\n"
    "• the area you cover\n"
    "• when you're available\n"
    "• what you charge\n\n"
    "Also share your phone number."
)
ASK_PHONE = "One last thing: share your phone number. You go live as soon as it's shared."
ASK_CHANGE = "✏️ Tell me what to change (voice or text)."
SORRY = "Sorry, something went wrong. Please send that again."
STALE_CHOICE = "That button is out of date; use the latest one."

CONFIRM_REPLIES = {
    businesses.ConfirmOutcome.LIVE: "🚀 You're live. Job requests will arrive here.",
    businesses.ConfirmOutcome.UPDATED: "✅ Profile updated.",
    businesses.ConfirmOutcome.NEEDS_BASICS: "Please tell me your business name and area first.",
    businesses.ConfirmOutcome.STALE: "That card is out of date; use the latest one.",
}


def text(message: str) -> Reply:
    return Reply(kind=ReplyKind.TEXT, text=message)


def ask_contact(message: str = ASK_PHONE) -> Reply:
    return Reply(kind=ReplyKind.ASK_CONTACT, text=message)


def language_choice() -> Reply:
    return Reply(
        kind=ReplyKind.CHOICES,
        text=LANGUAGE_PROMPT,
        choices=[
            Choice(value=f"{LANGUAGE}:{code}", label=label) for code, label in LANGUAGES.items()
        ],
    )


def language_picked(value: str) -> str | None:
    """The language label if `value` is a language choice, else None."""
    action, _, code = value.partition(":")
    return LANGUAGES.get(code) if action == LANGUAGE else None


def profile_card(
    profile: businesses.Profile, phone: str | None, title: str, footer: str = ""
) -> Reply:
    def v(value: str | None) -> str:
        return value or "-"

    return Reply(
        kind=ReplyKind.CARD,
        title=title,
        text=footer,
        fields=[
            CardField(label="👤 Name", value=v(profile.name)),
            CardField(label="🛠 Trade", value=businesses.trade_label(profile.trade)),
            CardField(label="📍 Area", value=v(profile.area)),
            CardField(label="📞 Phone", value=phone or "not shared yet"),
            CardField(label="🕒 Availability", value=v(profile.availability_text)),
            CardField(label="💶 Prices", value=v(profile.pricing_text)),
            CardField(label="📄 Quoted separately", value=v(profile.quoted_separately)),
        ],
    )


def proposal_card(proposal: businesses.ProposalView) -> Reply:
    """The card the seller confirms. Without name or area it asks for them and has no Correct."""
    title = (
        "✏️ Updated profile (not saved yet)"
        if proposal.business_status == businesses.BusinessStatus.ACTIVE
        else "📝 Your profile (not live yet)"
    )
    if proposal.missing_basics:
        missing = " and ".join(proposal.missing_basics)
        return profile_card(
            proposal.profile, proposal.phone, title, f"Almost there! Please tell me your {missing}."
        )
    card = profile_card(proposal.profile, proposal.phone, title)
    card.choices = [
        Choice(value=f"{CONFIRM}:{proposal.proposal_id}", label="✅ Correct"),
        Choice(value=f"{CHANGE}:{proposal.proposal_id}", label="✏️ Change"),
    ]
    return card


def live_card(business: businesses.BusinessView) -> Reply:
    title = (
        "✅ Your live profile"
        if business.status == businesses.BusinessStatus.ACTIVE
        else "📝 Draft (not live)"
    )
    return profile_card(business.profile(), business.phone, title)


def phone_offer(phone: str) -> Reply:
    return Reply(
        kind=ReplyKind.CHOICES,
        text=f"Save {phone} as your phone number?",
        choices=[
            Choice(value=f"{PHONE}:{phone}", label="✅ Yes, save it"),
            Choice(value=PHONE_NO, label="✖️ No"),
        ],
    )


def confirm_outcome(outcome: businesses.ConfirmOutcome) -> Reply:
    if outcome == businesses.ConfirmOutcome.NEEDS_PHONE:
        return ask_contact()
    return text(CONFIRM_REPLIES[outcome])
