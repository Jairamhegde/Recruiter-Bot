"""The internal key that identifies a stored record (D-53).

Names and titles aren't unique, so the writers and the seed can't use them to recognise a record.
A seed record's key comes from its name, so running the seed again finds it and adds nobody twice.
A record added through the API gets a random key, so two people with the same name are two records.
"""
import uuid


def source_key_for(source: str, slug: str) -> str:
    """'seed:sherlock-h' for a seed record; 'api:<random id>' for one added any other way."""
    if source == "seed":
        return f"seed:{slug}"
    return f"{source}:{uuid.uuid4().hex}"
