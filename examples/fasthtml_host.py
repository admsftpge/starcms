"""Demo: the same starcms mounted in a FastHTML app.

Run from the repo root:  uv run poe demo-fasthtml
Then visit:              http://localhost:8000/admin/  (log in: admin / admin)
"""

import os

import pydantic
from fasthtml import common as fh

import starcms

# Demo-only convenience; never default credentials like this in production.
os.environ.setdefault("STARCMS_ADMIN_USER", "admin")
os.environ.setdefault("STARCMS_ADMIN_PASSWORD", "admin")


class BlogPost(pydantic.BaseModel):
    title: str
    body: str | None = None
    published: bool = False


app = fh.FastHTML()
rt = app.route

cms = starcms.StarCMS(db="sqlite+aiosqlite:///demo.db", models=[BlogPost])
cms.mount(app, admin="/admin")


@rt("/")
async def home():
    # The in-process query face: the site reads its own content directly —
    # no HTTP round-trip to itself, no JSON API needed.
    posts = await cms.find(BlogPost, published=True)
    return fh.Div(
        fh.H1("Host FastHTML site"),
        fh.Ul(*[fh.Li(post["title"]) for post in posts])
        if posts
        else fh.P("No published posts yet — write one in the admin."),
        fh.A("Go to the starcms admin", href="/admin/"),
    )
