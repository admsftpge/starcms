# starcms

[![CI](https://github.com/admsftpge/starcms/actions/workflows/ci.yml/badge.svg)](https://github.com/admsftpge/starcms/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/starcms)](https://pypi.org/project/starcms/)

A code-first CMS for Python. Define your content models as Pydantic classes
and get a login-protected admin UI plus a content API, mounted into your
existing **FastAPI** or **FastHTML** app — pure Python, no Node, no build
step, no separate service.

```python
from fastapi import FastAPI          # or: from fasthtml.common import FastHTML
from pydantic import BaseModel
from starcms import StarCMS

class BlogPost(BaseModel):
    title: str
    body: str | None = None
    published: bool = False

app = FastAPI()
cms = StarCMS(db="sqlite+aiosqlite:///content.db", models=[BlogPost])
cms.mount(app, admin="/admin", api="/api/cms")
```

That's the whole integration. From one model class you get:

- **`/admin`** — a server-rendered admin: list, create, edit, delete, behind
  a login, with forms generated from your model's fields and validated by
  Pydantic.
- **`/api/cms/blogpost`** — a read-only JSON API serving your content to
  frontends and mobile apps (opt-in: mounted only if you pass `api=`).
  Collections come enveloped as `{"items": [...]}` and paged
  (`?limit=` default 50, max 200, plus `?offset=`); single records live at
  `/api/cms/blogpost/{id}`.
- **In-process queries** — server-rendered hosts read their own content
  directly, no HTTP round-trip to yourself. Records come back as plain
  dicts (`{"id": ..., **fields}`):

  ```python
  posts = await cms.find(BlogPost, published=True, limit=10)
  post = await cms.get(BlogPost, 42)
  ```

Change the class and the admin forms, table, database schema, and API all
follow. The model is the single source of truth.

## Why

Python is underserved for modern, code-first content management. Wagtail and
Django CMS are mature but Django-coupled; the popular headless CMSes
(Payload, Strapi, Sanity) mean running a Node service next to your Python
app — two runtimes, two deploys, and your content schema living outside your
codebase. Admin generators like SQLAdmin solve the screens but stop there:
no content delivery, and your models must be SQLAlchemy ORM classes.

starcms is a library, not a service: `pip install`, describe content in the
Pydantic vocabulary you already use, mount, done. It works in both FastAPI
and FastHTML because it's built one layer down, on Starlette — the
foundation they share.

## Install & run

```bash
uv add starcms        # or: pip install starcms
```

Set the admin credentials and (in production) a session secret:

| Variable | Purpose |
|---|---|
| `STARCMS_ADMIN_USER` / `STARCMS_ADMIN_PASSWORD` | The single admin login. Unset = admin locked. |
| `STARCMS_SECRET` | Signs the session cookie. Unset = random per process (dev-only; restarts log you out). Set it **before** `cms.mount()`. |

Then run your app as usual (`uvicorn myapp:app`). The database tables are
created automatically on first use — no migration step. SQLite
(`sqlite+aiosqlite:///...`) for development, PostgreSQL for production
(`postgresql+asyncpg://...` — install via `pip install "starcms[postgres]"`).

## Supported field types

`str`, `int`, `float`, `bool`, `datetime.datetime` — each optionally
`| None`, with defaults and `default_factory` respected (a
`default_factory=datetime.now` prefills forms with *now*, not server start).
Labels come from field names or `Field(title=...)`. Unsupported types are
rejected loudly at startup, not deep in a request. Models must not declare
an `id` field — starcms manages the primary key.

## The shape of it

```
your Pydantic models
        │  introspection (one pass, cached)
        ▼
   FieldSpec IR  ──────────┬───────────────┬──────────────┐
        │                  │               │              │
        ▼                  ▼               ▼              ▼
  database tables     admin forms     admin tables    JSON API
  (SQLAlchemy Core)   (htpy, no JS)                  (read-only)
```

One introspection layer reads your models; everything else is generated
from its output. The admin is a self-contained Starlette sub-app with its
own session (cookie named and path-scoped so it never collides with your
app's). The API is a second sub-app with a separate perimeter: no session,
no login — front it with your own auth if your content isn't public.

## Honest scope

This is the wedge, deliberately small: CRUD admin + content API. Not yet
here: rich text, media uploads, drafts/versioning, multi-user auth & roles,
migrations (schema changes during dev: drop and recreate), localization,
htmx interactivity. These arrive based on real demand, not speculation.

## Development

```bash
git clone https://github.com/admsftpge/starcms && cd starcms
uv sync
uv run poe check          # lint + tests
uv run poe demo-fastapi   # admin at http://localhost:8000/admin (admin/admin)
uv run poe demo-fasthtml  # same CMS, FastHTML host, content on the homepage
```

## License

MIT
