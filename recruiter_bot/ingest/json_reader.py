import json
from pathlib import Path
from typing import Any


def read_json_records(path: Path) -> list[Any]:
    """Reads a JSON file that holds an array of records."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name}: expected a JSON array of records, got {type(data).__name__}")
    return data
