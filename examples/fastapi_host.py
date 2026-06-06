"""Demo: starcms mounted in a FastAPI app.

Run from the repo root:  uv run poe demo-fastapi
Then visit:              http://localhost:8000/admin/  (log in: admin / admin)
"""

import os

import fastapi
import pydantic

import starcms

# Demo-only convenience; never default credentials like this in production.
os.environ.setdefault("STARCMS_ADMIN_USER", "admin")
os.environ.setdefault("STARCMS_ADMIN_PASSWORD", "admin")


class BlogPost(pydantic.BaseModel):
    title: str
    body: str | None = None
    published: bool = False


app = fastapi.FastAPI()


@app.get("/api/ping")
def ping() -> dict:
    return {"service": "the host app still owns everything outside /admin"}


cms = starcms.StarCMS(db="sqlite+aiosqlite:///demo.db", models=[BlogPost])
cms.mount(app, admin="/admin")
