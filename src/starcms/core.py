"""The developer-facing facade: models + storage in, mountable apps out."""

import typing

import pydantic
from starlette import applications

# Fully-qualified imports: the natural module names (db, admin, api) are
# taken by this class's public parameters.
import starcms.admin
import starcms.api
import starcms.db
import starcms.schema


class StarCMS:
    """One object wiring the developer's models to storage, admin, and API.

    Usage::

        cms = StarCMS(db="sqlite+aiosqlite:///content.db", models=[BlogPost])
        cms.mount(app, admin="/admin", api="/api/cms")   # app: FastAPI or FastHTML

        posts = await cms.find(BlogPost, published=True)  # in-process reads
    """

    def __init__(
        self, db: str, models: typing.Sequence[type[pydantic.BaseModel]]
    ) -> None:
        self.models = tuple(models)
        self._models_by_key: dict[str, type[pydantic.BaseModel]] = {}
        for model in self.models:
            key = starcms.schema.model_key(model)
            if key in self._models_by_key:
                raise ValueError(
                    f"Models {self._models_by_key[key].__name__} and "
                    f"{model.__name__} share the key {key!r}; model names "
                    "must be unique case-insensitively."
                )
            self._models_by_key[key] = model
        self.database = starcms.db.Database(db, self.models)

    def model_by_key(self, key: str) -> type[pydantic.BaseModel] | None:
        """The registered model whose schema.model_key matches, if any."""
        return self._models_by_key.get(key)

    def mount(
        self,
        app: applications.Starlette,
        admin: str = "/admin",
        api: str | None = None,
    ) -> None:
        """Mount the admin (and optionally the content API) into a host app.

        Typed as Starlette because that is the honest contract: FastAPI and
        FastHTML are both Starlette subclasses, and `app.mount()` is the
        shared ASGI mechanism they all inherit. The API mounts only when a
        path is given — it's opt-in surface area.
        """
        app.mount(admin, starcms.admin.build_app(self, mount_path=admin))
        if api is not None:
            app.mount(api, starcms.api.build_app(self))

    # --- the in-process query face ------------------------------------
    # For hosts that render content server-side (e.g. FastHTML): reading
    # your own content must not require an HTTP round-trip to yourself.

    async def get(
        self, model: type[pydantic.BaseModel], record_id: int
    ) -> dict[str, typing.Any] | None:
        """One stored record, or None.

        Records are plain dicts (id + fields) — the stable row contract.
        """
        return await self.database.repo(model).get(record_id)

    async def find(
        self,
        model: type[pydantic.BaseModel],
        /,
        *,
        limit: int | None = None,
        offset: int = 0,
        where: dict[str, typing.Any] | None = None,
        **filters: typing.Any,
    ) -> list[dict[str, typing.Any]]:
        """Stored records in id order, as plain dicts (id + fields — the
        stable row contract). Keyword filters are field-equality sugar:

            await cms.find(BlogPost, published=True, limit=10)

        Fields whose names collide with these parameters (limit, offset,
        where) can be filtered through the explicit where dict instead.
        """
        return await self.database.repo(model).list(
            limit=limit, offset=offset, where={**(where or {}), **filters}
        )

    async def create(self, instance: pydantic.BaseModel) -> int:
        """Store a validated instance; returns the new record's id."""
        return await self.database.repo(type(instance)).create(instance)
