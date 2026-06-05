"""Integration: the same admin app mounts into both FastAPI and FastHTML.

This is the project's central architectural claim, so both hosts get the
same three assertions: admin reachable, admin shows our content, host's own
routes unaffected.
"""

import fastapi
from fasthtml import common as fh
from starlette import testclient

import sample_models
import starcms


def make_cms(tmp_path) -> starcms.StarCMS:
    return starcms.StarCMS(
        db=f"sqlite+aiosqlite:///{tmp_path}/mount.db", models=[sample_models.Article]
    )


class TestFastAPIHost:
    def test_admin_mounts_and_host_routes_survive(self, tmp_path):
        app = fastapi.FastAPI()

        @app.get("/api/ping")
        def ping() -> dict:
            return {"ok": True}

        make_cms(tmp_path).mount(app, admin="/admin")
        client = testclient.TestClient(app)

        admin_page = client.get("/admin/")
        assert admin_page.status_code == 200
        assert "starcms admin" in admin_page.text
        assert "Article" in admin_page.text
        assert client.get("/api/ping").json() == {"ok": True}


class TestFastHTMLHost:
    def test_admin_mounts_and_host_routes_survive(self, tmp_path):
        app = fh.FastHTML()
        rt = app.route

        @rt("/")
        def home():
            return fh.H1("host site")

        make_cms(tmp_path).mount(app, admin="/admin")
        client = testclient.TestClient(app)

        admin_page = client.get("/admin/")
        assert admin_page.status_code == 200
        assert "starcms admin" in admin_page.text
        assert "Article" in admin_page.text
        assert "host site" in client.get("/").text


class TestMountPath:
    def test_custom_mount_prefix(self, tmp_path):
        app = fastapi.FastAPI()
        make_cms(tmp_path).mount(app, admin="/cms-backoffice")
        client = testclient.TestClient(app)

        assert client.get("/cms-backoffice/").status_code == 200

    def test_bare_prefix_redirects_to_slash(self, tmp_path):
        app = fastapi.FastAPI()
        make_cms(tmp_path).mount(app, admin="/admin")
        client = testclient.TestClient(app)

        # Starlette's mount redirects /admin -> /admin/; users will type both.
        assert client.get("/admin", follow_redirects=True).status_code == 200
