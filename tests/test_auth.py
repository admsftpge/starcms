"""Tests for the admin auth gate, login flow, and CSRF protection."""

import pytest
from starlette import applications, testclient

from conftest import csrf_from


@pytest.fixture
def raw_client(cms) -> testclient.TestClient:
    """An anonymous plain TestClient (no CSRF auto-injection)."""
    host = applications.Starlette()
    cms.mount(host, admin="/admin")
    return testclient.TestClient(host)


class TestGate:
    def test_anonymous_requests_redirect_to_login(self, raw_client):
        response = raw_client.get("/admin/article", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].endswith("/admin/login")

    def test_login_page_is_reachable_anonymously(self, raw_client):
        page = raw_client.get("/admin/login")
        assert page.status_code == 200
        assert 'name="username"' in page.text
        assert 'type="password"' in page.text

    def test_session_cookie_is_scoped_named_and_httponly(self, raw_client):
        cookie = raw_client.get("/admin/login").headers["set-cookie"].lower()
        # Name + path scoping is what prevents collisions with the host
        # app's own session cookie (e.g. FastHTML's default 'session').
        assert "starcms_session=" in cookie
        assert "path=/admin" in cookie
        assert "httponly" in cookie


class TestLogin:
    def test_wrong_password_is_rejected(self, raw_client):
        token = csrf_from(raw_client.get("/admin/login").text)
        response = raw_client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong", "csrf_token": token},
        )
        assert response.status_code == 401
        assert "Invalid credentials." in response.text
        # Still locked out.
        assert (
            raw_client.get("/admin/", follow_redirects=False).status_code == 303
        )

    def test_correct_credentials_grant_access(self, raw_client, login):
        login(raw_client)
        page = raw_client.get("/admin/")
        assert page.status_code == 200
        assert "starcms admin" in page.text

    def test_unconfigured_credentials_lock_the_admin(self, raw_client, monkeypatch):
        monkeypatch.delenv("STARCMS_ADMIN_USER")
        monkeypatch.delenv("STARCMS_ADMIN_PASSWORD")

        token = csrf_from(raw_client.get("/admin/login").text)
        response = raw_client.post(
            "/admin/login",
            data={"username": "admin", "password": "hunter2", "csrf_token": token},
        )
        assert response.status_code == 401  # locked, not open


class TestCsrf:
    def test_login_post_without_token_is_403(self, raw_client):
        raw_client.get("/admin/login")  # establishes a session
        response = raw_client.post(
            "/admin/login", data={"username": "admin", "password": "hunter2"}
        )
        assert response.status_code == 403

    def test_create_post_with_wrong_token_is_403(self, client):
        # client auto-injects the right token; an explicit one wins over it.
        response = client.post(
            "/admin/article/new",
            data={"title": "t", "views": "0", "rating": "0", "csrf_token": "wrong"},
        )
        assert response.status_code == 403
        assert "Nothing here yet." in client.get("/admin/article").text

    def test_delete_post_with_missing_token_is_403(self, client):
        client.post("/admin/article/new", data={"title": "keep", "views": "0", "rating": "0"})
        response = client.post("/admin/article/1/delete", data={"csrf_token": ""})
        assert response.status_code == 403
        assert "keep" in client.get("/admin/article").text

    def test_forms_carry_the_token(self, client):
        assert 'name="csrf_token"' in client.get("/admin/article/new").text


class TestLogout:
    def test_logout_clears_the_session(self, client):
        assert client.get("/admin/").status_code == 200

        response = client.post("/admin/logout", follow_redirects=False)
        assert response.status_code == 303

        assert client.get("/admin/", follow_redirects=False).status_code == 303

    def test_home_offers_a_logout_button(self, client):
        page = client.get("/admin/")
        assert "/admin/logout" in page.text
        assert "Log out" in page.text
