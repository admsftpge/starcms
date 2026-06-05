# starcms

A code-first CMS for Python. Define your content models as Pydantic classes and
get a generated admin UI and content API, mounted into your existing FastAPI or
FastHTML app.

> **Status: early development.** This release reserves the package name while
> v0.1 is being built. Follow along at
> [github.com/admsftpge/starcms](https://github.com/admsftpge/starcms).

```python
from fastapi import FastAPI
from pydantic import BaseModel
from starcms import StarCMS

class BlogPost(BaseModel):
    title: str
    body: str
    published: bool

app = FastAPI()
cms = StarCMS(db="sqlite:///content.db", models=[BlogPost])
cms.mount(app, admin="/admin", api="/api/cms")
```

*(API sketch — subject to change before v0.1.)*
