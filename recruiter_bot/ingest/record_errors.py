from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError


@dataclass(frozen=True)
class RecordError:
    index: int
    payload: Any
    message: str


def describe_validation_error(error: ValidationError) -> str:
    """'skills: List should have at least 1 item ...; experience_years: ...'"""
    messages = []
    for problem in error.errors():
        field_path = ".".join(str(part) for part in problem["loc"])
        if field_path == "":
            field_path = "record"
        messages.append(f"{field_path}: {problem['msg']}")
    return "; ".join(messages)
