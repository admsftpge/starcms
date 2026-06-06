"""Integration: the same admin app mounts into both FastAPI and FastHTML.

This is the project's central architectural claim, so both hosts get the
same assertions: admin reachable (after login), admin shows our content,
host's own routes unaffected.
"""

import fastapi
from fasthtml import common as fh
from starlette import testclient


class TestFastAPIHost:
    def test_admin_mounts_and_host_routes_survive(self, cms, login):
        app = fastapi.FastAPI()

        @app.get("/api/ping")
        def ping() -> dict:
            return {"ok": True}

        cms.mount(app, admin="/admin")
        client = testclient.TestClient(app)
        login(client)

        admin_page = client.get("/admin/")
        assert admin_page.status_code == 200
        assert "starcms admin" in admin_page.text
        assert "Article" in admin_page.text
        assert client.get("/api/ping").json() == {"ok": True}


class TestFastHTMLHost:
    def test_admin_mounts_and_host_routes_survive(self, cms, login):
        app = fh.FastHTML()
        rt = app.route

        @rt("/")
        def home():
            return fh.H1("host site")

        cms.mount(app, admin="/admin")
        client = testclient.TestClient(app)
        login(client)

        admin_page = client.get("/admin/")
        assert admin_page.status_code == 200
        assert "starcms admin" in admin_page.text
        assert "Article" in admin_page.text
        assert "host site" in client.get("/").text


class TestMountPath:
    def test_custom_mount_prefix(self, cms, login):
        app = fastapi.FastAPI()
        cms.mount(app, admin="/cms-backoffice")
        client = testclient.TestClient(app)
        login(client, base="/cms-backoffice")

        assert client.get("/cms-backoffice/").status_code == 200

    def test_bare_prefix_redirects_to_slash(self, cms):
        app = fastapi.FastAPI()
        cms.mount(app, admin="/admin")
        client = testclient.TestClient(app)

        # /admin -> /admin/ (mount redirect) -> /admin/login (auth gate);
        # the chain ends on a real page either way.
        response = client.get("/admin", follow_redirects=True)
        assert response.status_code == 200