"""Tests for the admin views (home, list, create, edit, delete) and lazy init."""

import datetime
import re

import sample_models
from conftest import seed

# Minimal valid create/edit payload; tests override fields via `VALID_FORM | {...}`.
VALID_FORM = {"title": "t", "views": "0", "rating": "0"}


def input_tag(html: str, name: str) -> str:
    """Extract one <input> by name, so attribute assertions don't depend on
    htpy's attribute ordering."""
    match = re.search(f'<input[^>]*name="{name}"[^>]*>', html)
    assert match, f"no input named {name}"
    return match.group(0)


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
        client.post("/admin/article/new", data=VALID_FORM | {"published": "on"})
        assert "✓" in client.get("/admin/article").text

    def test_datetime_round_trips(self, client):
        client.post(
            "/admin/article/new",
            data=VALID_FORM | {"published_at": "2026-06-05T12:30"},
        )
        assert "2026-06-05 12:30:00" in client.get("/admin/article").text

    def test_invalid_input_rerenders_with_errors_and_preserved_input(self, client):
        response = client.post(
            "/admin/article/new",
            data=VALID_FORM | {"title": "Kept title", "views": "not-a-number"},
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
        client.post("/admin/article/new", data=VALID_FORM | {"body": ""})
        page = client.get("/admin/article")
        assert page.status_code == 200  # None renders as blank cell, no crash


class TestEditForm:
    def test_form_prefills_stored_values(self, client, db_url):
        seed(
            db_url,
            sample_models.Article(title="Stored title", views=9, published=True),
        )

        page = client.get("/admin/article/1/edit")
        assert page.status_code == 200
        assert 'value="Stored title"' in input_tag(page.text, "title")
        assert 'value="9"' in input_tag(page.text, "views")
        assert "checked" in input_tag(page.text, "published")

    def test_list_id_links_to_edit_page(self, client, db_url):
        seed(db_url, sample_models.Article(title="t"))

        page = client.get("/admin/article")
        assert "/admin/article/1/edit" in page.text

    def test_valid_post_updates_and_redirects(self, client, db_url):
        seed(db_url, sample_models.Article(title="Before"))

        response = client.post(
            "/admin/article/1/edit",
            data=VALID_FORM | {"title": "After", "views": "5"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get("/admin/article")
        assert "After" in page.text
        assert "Before" not in page.text

    def test_noop_resave_preserves_datetime_seconds(self, client, db_url):
        seed(
            db_url,
            sample_models.Article(
                title="t",
                published_at=datetime.datetime(2026, 6, 5, 12, 30, 45),
            ),
        )

        # The fidelity guarantee: open edit -> the form carries full seconds.
        page = client.get("/admin/article/1/edit")
        assert 'value="2026-06-05T12:30:45"' in input_tag(page.text, "published_at")

        # Resave exactly what the form showed; seconds must survive.
        client.post(
            "/admin/article/1/edit",
            data=VALID_FORM | {"published_at": "2026-06-05T12:30:45"},
        )
        assert "12:30:45" in client.get("/admin/article").text

    def test_invalid_post_rerenders_and_preserves_db(self, client, db_url):
        seed(db_url, sample_models.Article(title="Untouched"))

        response = client.post(
            "/admin/article/1/edit",
            data=VALID_FORM | {"views": "garbage"},
        )
        assert response.status_code == 422
        # The error page is the full edit page: Delete must still be there.
        assert "/admin/article/1/delete" in response.text

        assert "Untouched" in client.get("/admin/article").text

    def test_missing_record_is_404(self, client):
        assert client.get("/admin/article/999/edit").status_code == 404
        response = client.post(
            "/admin/article/999/edit", data=VALID_FORM, follow_redirects=False
        )
        assert response.status_code == 404


class TestDelete:
    def test_delete_button_lives_on_edit_page(self, client, db_url):
        seed(db_url, sample_models.Article(title="t"))

        page = client.get("/admin/article/1/edit")
        assert "/admin/article/1/delete" in page.text
        assert "Delete" in page.text

    def test_post_deletes_and_redirects(self, client, db_url):
        seed(db_url, sample_models.Article(title="Doomed"))

        response = client.post(
            "/admin/article/1/delete", follow_redirects=False
        )
        assert response.status_code == 303

        page = client.get("/admin/article")
        assert "Doomed" not in page.text
        assert "Nothing here yet." in page.text

    def test_delete_missing_record_is_404(self, client):
        assert client.post("/admin/article/999/delete").status_code == 404

    def test_delete_requires_post(self, client, db_url):
        seed(db_url, sample_models.Article(title="Safe"))

        # GET must never delete: crawlers and prefetchers follow links.
        assert client.get("/admin/article/1/delete").status_code == 405
        assert "Safe" in client.get("/admin/article").text
