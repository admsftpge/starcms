"""Shared fixtures for the test suite."""

import re

import pytest
from starlette import applications, testclient

import sample_models
import starcms
from starcms import db

CSRF_RE = re.compile('name="csrf_token" value="([^"]*)"')


def csrf_from(html: str) -> str:
    """Extract the CSRF token a rendered form carries."""
    match = CSRF_RE.search(html)
    assert match, "page should carry a CSRF token"
    return match.group(1)


@pytest.fixture(autouse=True)
def admin_credentials(monkeypatch):
    """Every test runs with a configured admin login and a stable secret."""
    monkeypatch.setenv("STARCMS_ADMIN_USER", "admin")
    monkeypatch.setenv("STARCMS_ADMIN_PASSWORD", "hunter2")
    monkeypatch.setenv("STARCMS_SECRET", "test-secret")


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


class CsrfClient(testclient.TestClient):
    """TestClient that injects the session CSRF token into POST form data,
    keeping CRUD tests focused on their own behavior. Tests exercising
    CSRF rejection pass an explicit csrf_token (which wins over the
    injected one) or use a plain TestClient."""

    csrf = ""

    def post(self, url, *, data=None, **kwargs):
        return super().post(
            url, data={"csrf_token": self.csrf, **(data or {})}, **kwargs
        )


@pytest.fixture
def login():
    """A callable that logs a client into a mounted admin."""

    def _login(client, base="/admin", username="admin", password="hunter2"):
        token = csrf_from(client.get(f"{base}/login").text)
        response = client.post(
            f"{base}/login",
            data={"username": username, "password": password, "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303, "login should have succeeded"
        if isinstance(client, CsrfClient):
            client.csrf = token
        return token

    return _login


@pytest.fixture
def client(cms, login) -> CsrfClient:
    """A CsrfClient logged into the admin mounted at /admin."""
    host = applications.Starlette()
    cms.mount(host, admin="/admin")
    c = CsrfClient(host)
    login(c)
    return c
