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


# Words dropped from a root key, and the suffixes stripped from each word.
ROOT_FILLER_WORDS = {"a", "an", "the", "of", "in", "on", "for", "to", "with", "and", "skill", "skills"}
ROOT_SUFFIXES = ("ments", "ment", "ings", "ing", "ions", "ion", "ed", "es", "s")
MIN_ROOT_LENGTH = 4


def root_key(slug: str) -> str:
    """'managing-products' and 'product-management' -> 'manag-product'. Word order doesn't matter."""
    roots = {_root_word(word) for word in slug.split("-") if word not in ROOT_FILLER_WORDS}
    if not roots:
        return slug
    return "-".join(sorted(roots))


def _root_word(word: str) -> str:
    """Deliberately conservative: a missed match costs less than a wrong one."""
    stripped = False
    for suffix in ROOT_SUFFIXES:
        if not word.endswith(suffix) or len(word) - len(suffix) < MIN_ROOT_LENGTH:
            continue
        stem = word[: -len(suffix)]
        if suffix in ("ion", "ions") and not stem.endswith("t"):
            continue  # negotiation -> negotiat, but mission stays mission
        if suffix == "s" and word.endswith(("ss", "us", "is")):
            continue  # process, status, analysis
        word = stem
        stripped = True
        break
    if word.endswith("e") and len(word) > MIN_ROOT_LENGTH:
        word = word[:-1]  # manage -> manag, so it meets management and managing
    if stripped and len(word) > MIN_ROOT_LENGTH and word[-1] == word[-2] and word[-1] not in "slzf":
        word = word[:-1]  # planning -> plan, but staffing keeps staff
    return word


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
