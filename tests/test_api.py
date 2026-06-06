"""Tests for the JSON content API (the second mounted app)."""

import datetime

import pytest
from starlette import applications, testclient

import sample_models
from conftest import seed


@pytest.fixture
def api_client(cms) -> testclient.TestClient:
    """Admin + API mounted side by side, the way a real host would."""
    host = applications.Starlette()
    cms.mount(host, admin="/admin", api="/api/cms")
    return testclient.TestClient(host)


class TestCollection:
    def test_empty_collection_is_an_enveloped_empty_list(self, api_client):
        response = api_client.get("/api/cms/article")
        assert response.status_code == 200
        # Enveloped so pagination metadata can be added without breakage.
        assert response.json() == {"items": []}

    def test_rows_serialize_with_ids_and_iso_datetimes(self, api_client, db_url):
        seed(
            db_url,
            sample_models.Article(
                title="Hello",
                published=True,
                published_at=datetime.datetime(2026, 6, 6, 9, 30),
            ),
        )

        rows = api_client.get("/api/cms/article").json()["items"]
        assert rows == [
            {
                "id": 1,
                "title": "Hello",
                "body": None,
                "views": 0,
                "rating": 0.0,
                "published": True,
                "published_at": "2026-06-06T09:30:00",
            }
        ]

    def test_limit_and_offset_query_params(self, api_client, db_url):
        seed(db_url, *(sample_models.Article(title=t) for t in "abcd"))

        rows = api_client.get("/api/cms/article?limit=2&offset=1").json()["items"]
        assert [r["title"] for r in rows] == ["b", "c"]

    def test_negative_limit_is_clamped_not_unbounded(self, api_client, db_url):
        # SQLite treats LIMIT -1 as "no limit"; the clamp must prevent that.
        seed(db_url, *(sample_models.Article(title=t) for t in "abc"))

        rows = api_client.get("/api/cms/article?limit=-1").json()["items"]
        assert len(rows) == 1

    def test_non_integer_paging_is_400(self, api_client):
        assert api_client.get("/api/cms/article?limit=lots").status_code == 400

    def test_unknown_model_is_404(self, api_client):
        assert api_client.get("/api/cms/nonsense").status_code == 404


class TestItem:
    def test_item_by_id(self, api_client, db_url):
        seed(db_url, sample_models.Article(title="One"))

        item = api_client.get("/api/cms/article/1")
        assert item.status_code == 200
        assert item.json()["title"] == "One"

    def test_missing_item_is_404(self, api_client):
        assert api_client.get("/api/cms/article/999").status_code == 404


class TestPerimeters:
    def test_api_requires_no_login(self, api_client):
        # The defining difference from the admin: public reads, no session.
        response = api_client.get("/api/cms/article")
        assert response.status_code == 200
        assert "set-cookie" not in response.headers

    def test_admin_stays_gated_next_door(self, api_client):
        response = api_client.get("/admin/article", follow_redirects=False)
        assert response.status_code == 303

    def test_api_is_absent_unless_opted_in(self, cms):
        host = applications.Starlette()
        cms.mount(host, admin="/admin")  # no api=

        client = testclient.TestClient(host)
        assert client.get("/api/cms/article").status_code == 404

    def test_api_is_read_only(self, api_client):
        assert api_client.post("/api/cms/article").status_code == 405
