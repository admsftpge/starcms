"""The developer-facing facade: models + storage in, mountable apps out."""

import typing

import pydantic
from starlette import applications

# Fully-qualified imports: the natural module names (db, admin) are taken by
# this class's public parameters.
import starcms.admin
import starcms.db


class StarCMS:
    """One object wiring the developer's models to storage and the admin.

    Usage::

        cms = StarCMS(db="sqlite+aiosqlite:///content.db", models=[BlogPost])
        cms.mount(app, admin="/admin")   # app: FastAPI or FastHTML
    """

    def __init__(
        self, db: str, models: typing.Sequence[type[pydantic.BaseModel]]
    ) -> None:
        self.models = tuple(models)
        self.database = starcms.db.Database(db, self.models)

    def mount(self, app: applications.Starlette, admin: str = "/admin") -> None:
        """Mount the admin into a host app at the given path prefix.

        Typed as Starlette because that is the honest contract: FastAPI and
        FastHTML are both Starlette subclasses, and `app.mount()` is the
        shared ASGI mechanism they all inherit.
        """
        app.mount(admin, starcms.admin.build_app(self, mount_path=admin))
