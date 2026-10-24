"""Money crosses the edges here only: amounts are integer minor units inside. (ADR 0002)"""

# ISO 4217 exponents that are not 2. Everything else uses 2.
_EXPONENTS = {"JPY": 0, "KRW": 0, "ISK": 0, "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3}
_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


def exponent(currency: str) -> int:
    return _EXPONENTS.get(currency.upper(), 2)


def to_minor(amount: float, currency: str) -> int:
    minor: int = round(amount * 10 ** exponent(currency))
    return minor


def format_minor(amount_minor: int, currency: str) -> str:
    exp = exponent(currency)
    value = amount_minor / 10**exp
    text = f"{value:.{exp}f}" if amount_minor % 10**exp else f"{value:.0f}"
    symbol = _SYMBOLS.get(currency.upper())
    return f"{symbol}{text}" if symbol else f"{text} {currency.upper()}"
