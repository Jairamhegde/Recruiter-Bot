import os
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from recruiter_bot import seed
from recruiter_bot.db import DEFAULT_DATABASE_URL, connect
from recruiter_bot.migrate import apply_pending

TEST_DATABASE_NAME = "recruiter_bot_test"


@pytest.fixture(scope="session")
def test_database():
    """Builds a throwaway database from the real migrations and seed data, and drops it afterwards."""
    development_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    test_url = urlunparse(urlparse(development_url)._replace(path=f"/{TEST_DATABASE_NAME}"))

    try:
        server = psycopg.connect(development_url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running")

    server.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE_NAME} WITH (FORCE)")
    server.execute(f"CREATE DATABASE {TEST_DATABASE_NAME}")

    environment = pytest.MonkeyPatch()
    environment.setenv("DATABASE_URL", test_url)

    try:
        with connect() as connection:
            connection.autocommit = True
            apply_pending(connection)

        seed.run()

        yield test_url
    finally:
        environment.undo()
        server.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE_NAME} WITH (FORCE)")
        server.close()


@pytest.fixture
def conn(test_database):
    """A connection to the test database."""
    with connect() as connection:
        yield connection
