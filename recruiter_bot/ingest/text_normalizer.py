import re
import unicodedata
from datetime import date, timedelta

SYMBOL_WORDS = {"+": "plus", "#": "sharp"}
DAYS_PER_UNIT = {"day": 1, "week": 7, "month": 30}


def normalize(text: str) -> str:
    """'  Stakeholder   Management ' -> 'stakeholder-management'"""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    lowered = ascii_text.strip().lower()
    for symbol, word in SYMBOL_WORDS.items():
        lowered = lowered.replace(symbol, word)
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    return hyphenated.strip("-")


def normalize_required(text: str, field_name: str) -> str:
    normalized = normalize(text)
    if normalized == "":
        raise ValueError(f"{field_name} {text!r} has no letters or digits")
    return normalized


def normalize_list(values: list[str], field_name: str) -> list[str]:
    """Normalizes each value and drops duplicates, keeping the original order."""
    result = []
    for value in values:
        normalized = normalize_required(value, field_name)
        if normalized not in result:
            result.append(normalized)
    return result


def compact_key(slug: str) -> str:
    """Must match the generated compact_key column in the database."""
    return slug.replace("-", "")


def parse_availability(text: str, today: date) -> tuple[bool, date | None]:
    """Returns (open_to_opportunities, available_from)."""
    value = " ".join(text.strip().lower().split())

    if value == "not looking":
        return False, None
    if value in ("immediate", "immediately", "now"):
        return True, today

    match = re.fullmatch(r"(\d+)\s*(day|week|month)s?", value)
    if match is None:
        raise ValueError(f"unrecognized availability {text!r}")

    amount = int(match.group(1))
    unit = match.group(2)
    return True, today + timedelta(days=amount * DAYS_PER_UNIT[unit])
