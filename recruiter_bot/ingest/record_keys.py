"""The internal key of a stored record: 'seed:<slug>' or 'api:<random id>'."""
import uuid


def source_key_for(source: str, slug: str) -> str:
    """'seed:sherlock-h' for a seed record; 'api:<random id>' for one added any other way."""
    if source == "seed":
        return f"seed:{slug}"
    return f"{source}:{uuid.uuid4().hex}"
