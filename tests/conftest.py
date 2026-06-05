"""Shared fixtures for the test suite."""

import pytest

import sample_models
import starcms
from starcms import db


@pytest.fixture
def db_url(tmp_path) -> str:
    """A per-test SQLite url.

    File-backed rather than :memory: because each async connection gets its
    own private in-memory database, which silently breaks multi-statement
    tests; tmp_path keeps it just as isolated and self-cleaning.
    """
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@pytest.fixture
def cms(db_url) -> starcms.StarCMS:
    """A StarCMS over the shared Article model."""
    return starcms.StarCMS(db=db_url, models=[sample_models.Article])


@pytest.fixture
async def database(db_url):
    """A Database with tables created, disposed after the test."""
    d = db.Database(db_url, models=[sample_models.Article])
    await d.create_all()
    yield d
    await d.dispose()


@pytest.fixture
async def repo(database):
    """The Article repository — what most CRUD tests actually want."""
    return database.repo(sample_models.Article)
