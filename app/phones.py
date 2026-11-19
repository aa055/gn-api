import re

from app.countries import COUNTRIES

# These functions only answer "what is this number?". Which error to return
# (INVALID_PHONE, PHONE_NEEDS_COUNTRY, ...) depends on the endpoint, so the
# routes in main.py decide that.


def clean(raw):
    """Strip spaces, hyphens and round brackets. None if anything odd is left."""
    cleaned = raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    # [0-9] rather than \d, because \d also matches Arabic-Indic digits
    if re.fullmatch(r"\+?[0-9]+", cleaned):
        return cleaned
    return None


def is_mobile(mobile, country):
    c = COUNTRIES[country]
    return mobile.startswith(c["mobile_start"]) and len(mobile) == c["mobile_length"]


def read_international(cleaned):
    """'+966551234567' or '966551234567' -> ('SA', '+966551234567'). None otherwise."""
    digits = cleaned.removeprefix("+")
    for country, c in COUNTRIES.items():
        if digits.startswith(c["dial"]) and is_mobile(digits[len(c["dial"]):], country):
            return country, "+" + digits
    return None


def read_national(cleaned, country):
    """'0551234567' read as SA -> '+966551234567'. None if it doesn't fit that country."""
    c = COUNTRIES[country]
    if cleaned.startswith("+") or not cleaned.startswith(c["trunk"]):
        return None
    mobile = cleaned[len(c["trunk"]):]
    if is_mobile(mobile, country):
        return "+" + c["dial"] + mobile
    return None
