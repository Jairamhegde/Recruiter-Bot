import os

import psycopg

# 127.0.0.1, not localhost: on Windows, localhost tries IPv6 first and Docker leaves it hanging.
DEFAULT_DATABASE_URL = "postgresql://recruiter:recruiter@127.0.0.1:5433/recruiter_bot"


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), connect_timeout=10)
