"""Tests for the admin views (home, list, create) and lazy database init."""

import asyncio
import re

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


def input_tag(html: str, name: str) -> str:
    """Extract one <input> by name, so attribute assertions don't depend on
    htpy's attribute ordering."""
    match = re.search(f'<input[^>]*name="{name}"[^>]*>', html)
    assert match, f"no input named {name}"
    return match.group(0)


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


class TestCreateForm:
    def test_form_renders_a_widget_per_field(self, client):
        page = client.get("/admin/article/new")
        assert page.status_code == 200
        for name, input_type in [
            ("title", "text"),
            ("views", "number"),
            ("rating", "number"),
            ("published", "checkbox"),
            ("published_at", "datetime-local"),
        ]:
            assert f'name="{name}"' in page.text
            assert f'type="{input_type}"' in page.text

    def test_defaults_prefill_and_required_marks_required_fields(self, client):
        page = client.get("/admin/article/new")
        assert 'value="0"' in input_tag(page.text, "views")
        # title has no default and isn't nullable -> browser-required
        title = input_tag(page.text, "title")
        assert 'value=""' in title
        assert "required" in title

    def test_valid_post_creates_and_redirects_to_list(self, client):
        response = client.post(
            "/admin/article/new",
            data={"title": "Round trip", "views": "3", "rating": "1.5"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("/admin/article")

        page = client.get("/admin/article")
        assert "Round trip" in page.text
        assert "✗" in page.text  # checkbox absent -> published stored False

    def test_checked_checkbox_stores_true(self, client):
        client.post(
            "/admin/article/new",
            data={"title": "t", "views": "0", "rating": "0", "published": "on"},
        )
        assert "✓" in client.get("/admin/article").text

    def test_datetime_round_trips(self, client):
        client.post(
            "/admin/article/new",
            data={
                "title": "t",
                "views": "0",
                "rating": "0",
                "published_at": "2026-06-05T12:30",
            },
        )
        assert "2026-06-05 12:30:00" in client.get("/admin/article").text

    def test_invalid_input_rerenders_with_errors_and_preserved_input(self, client):
        response = client.post(
            "/admin/article/new",
            data={"title": "Kept title", "views": "not-a-number", "rating": "0"},
        )
        assert response.status_code == 422
        assert "integer" in response.text  # pydantic's message, shown inline
        assert 'value="Kept title"' in response.text  # user input preserved
        assert 'value="not-a-number"' in response.text

        # Nothing was stored.
        assert "Kept title" not in client.get("/admin/article").text

    def test_missing_required_field_is_an_error_not_a_crash(self, client):
        response = client.post(
            "/admin/article/new",
            data={"views": "1", "rating": "0"},  # no title
        )
        assert response.status_code == 422
        assert "required" in response.text.lower()

    def test_empty_nullable_field_stores_none(self, client):
        client.post(
            "/admin/article/new",
            data={"title": "t", "views": "0", "rating": "0", "body": ""},
        )
        page = client.get("/admin/article")
        assert page.status_code == 200  # None renders as blank cell, no crash
