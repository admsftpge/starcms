"""Shared fixtures for the test suite."""

import pytest

import sample_models
from starcms import db


@pytest.fixture
async def database(tmp_path):
    """A file-backed SQLite Database with tables created, disposed after the test.

    File-backed rather than :memory: because each async connection gets its
    own private in-memory database, which silently breaks multi-statement
    tests; tmp_path keeps it just as isolated and self-cleaning.
    """
    d = db.Database(
        f"sqlite+aiosqlite:///{tmp_path}/test.db", models=[sample_models.Article]
    )
    await d.create_all()
    yield d
    await d.dispose()


@pytest.fixture
async def repo(database):
    """The Article repository — what most CRUD tests actually want."""
    return database.repo(sample_models.Article)
