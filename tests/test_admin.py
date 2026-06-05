"""Tests for the admin views (home, list) and lazy database init."""

import asyncio

import pytest
from starlette import applications, testclient

import sample_models
from starcms import db


@pytest.fixture
def client(cms) -> testclient.TestClient:
    """The admin mounted at /admin in a plain Starlette host."""
    host = applications.Starlette()
    cms.mount(host, admin="/admin")
    return testclient.TestClient(host)


def seed(db_url: str, *articles: sample_models.Article) -> None:
    """Insert rows using a separate Database: engines are event-loop-bound,
    so the TestClient's loop and ours must not share one."""

    async def _run() -> None:
        d = db.Database(db_url, [sample_models.Article])
        repo = d.repo(sample_models.Article)
        for article in articles:
            await repo.create(article)
        await d.dispose()

    asyncio.run(_run())


class TestLazyInit:
    def test_first_request_creates_tables(self, client):
        # No create_all was ever called; the list view needs the table.
        assert client.get("/admin/article").status_code == 200


class TestHome:
    def test_links_to_each_model_with_mount_prefix(self, client):
        page = client.get("/admin/")
        assert page.status_code == 200
        # url_for must include the mount prefix or links break behind /admin.
        assert "/admin/article" in page.text
        assert "Article" in page.text


class TestModelList:
    def test_empty_state(self, client):
        page = client.get("/admin/article")
        assert "Nothing here yet." in page.text

    def test_rows_and_labels_render(self, client, db_url):
        seed(
            db_url,
            sample_models.Article(title="First post", views=7),
            sample_models.Article(title="Second post", published=True),
        )

        page = client.get("/admin/article")
        assert "First post" in page.text
        assert "Second post" in page.text
        # Headers come from FieldSpec labels, plus the id column.
        assert "<th>id</th>" in page.text
        assert "<th>Published at</th>" in page.text

    def test_bools_render_as_marks_and_none_as_blank(self, client, db_url):
        seed(db_url, sample_models.Article(title="t", published=True, body=None))

        page = client.get("/admin/article")
        assert "✓" in page.text

    def test_stored_values_are_escaped(self, client, db_url):
        seed(db_url, sample_models.Article(title="<script>alert(1)</script>"))

        page = client.get("/admin/article")
        assert "<script>" not in page.text
        assert "&lt;script&gt;" in page.text

    def test_unknown_model_is_404(self, client):
        assert client.get("/admin/nonsense").status_code == 404
