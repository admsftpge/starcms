"""Demo: the same starcms mounted in a FastHTML app.

Run from the repo root:  uv run poe demo-fasthtml
Then visit:              http://localhost:8000/admin/
"""

import pydantic
from fasthtml import common as fh

import starcms


class BlogPost(pydantic.BaseModel):
    title: str
    body: str | None = None
    published: bool = False


app = fh.FastHTML()
rt = app.route


@rt("/")
def home():
    return fh.Div(
        fh.H1("Host FastHTML site"),
        fh.A("Go to the starcms admin", href="/admin/"),
    )


cms = starcms.StarCMS(db="sqlite+aiosqlite:///demo.db", models=[BlogPost])
cms.mount(app, admin="/admin")
