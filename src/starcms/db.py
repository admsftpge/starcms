"""Persistence layer: FieldSpecs become tables, models get CRUD repositories.

Built on SQLAlchemy Core (no ORM): starcms only needs table definitions plus
the four CRUD statements, and Core absorbs the SQLite/Postgres dialect
differences. Tables are constructed at runtime from FieldSpecs — the same
specs that drive form and API generation — so the database schema can never
drift from the model definition.
"""

import asyncio
import contextlib
import datetime
import typing

import pydantic
import sqlalchemy
from sqlalchemy.ext import asyncio as sa_async

from starcms import schema

# FieldSpec.python_type → SQLAlchemy column type. The supported type set is
# small enough that this map IS the entire storage mapping decision.
_COLUMN_TYPES: dict[type, typing.Any] = {
    str: sqlalchemy.Text,
    int: sqlalchemy.Integer,
    float: sqlalchemy.Float,
    bool: sqlalchemy.Boolean,
    datetime.datetime: sqlalchemy.DateTime,
}

# The map must cover exactly what introspection accepts — drift fails here,
# at import, instead of as a KeyError when someone's model hits table_for.
assert set(_COLUMN_TYPES) == set(schema.SUPPORTED_TYPES)

Row = dict[str, typing.Any]


def table_for(
    model: type[pydantic.BaseModel], metadata: sqlalchemy.MetaData
) -> sqlalchemy.Table:
    """Build a model's table: an autoincrement id plus one column per FieldSpec.

    introspect() has already rejected models declaring their own "id" field.
    """
    specs = schema.introspect(model)
    columns = [
        sqlalchemy.Column(
            schema.ID_FIELD, sqlalchemy.Integer, primary_key=True, autoincrement=True
        )
    ]
    columns += [
        sqlalchemy.Column(s.name, _COLUMN_TYPES[s.python_type], nullable=s.nullable)
        for s in specs
    ]
    return sqlalchemy.Table(schema.model_key(model), metadata, *columns)


class Repository:
    """CRUD for one model. Rows come back as plain dicts: {"id": ..., **fields}.

    Writes take validated model instances — Pydantic has already applied
    defaults and type checks by construction time, so nothing unvalidated
    can reach the database through this class.
    """

    def __init__(
        self,
        model: type[pydantic.BaseModel],
        table: sqlalchemy.Table,
        database: "Database",
    ) -> None:
        self._model = model
        self._table = table
        self._database = database

    def _check_instance(self, instance: pydantic.BaseModel) -> None:
        if not isinstance(instance, self._model):
            raise TypeError(
                f"expected a {self._model.__name__} instance, got {instance!r}"
            )

    async def create(self, instance: pydantic.BaseModel) -> int:
        """Insert a validated instance; returns the new row's id."""
        self._check_instance(instance)
        async with self._database.begin() as conn:
            result = await conn.execute(
                sqlalchemy.insert(self._table).values(**instance.model_dump())
            )
            return result.inserted_primary_key[0]

    async def get(self, record_id: int) -> Row | None:
        async with self._database.connect() as conn:
            result = await conn.execute(
                sqlalchemy.select(self._table).where(self._table.c.id == record_id)
            )
            row = result.mappings().first()
        return dict(row) if row is not None else None

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[Row]:
        stmt = sqlalchemy.select(self._table).order_by(self._table.c.id)
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._database.connect() as conn:
            result = await conn.execute(stmt)
            return [dict(r) for r in result.mappings()]

    async def update(self, record_id: int, instance: pydantic.BaseModel) -> bool:
        """Replace a row's fields with the instance's; True if the row existed."""
        self._check_instance(instance)
        async with self._database.begin() as conn:
            result = await conn.execute(
                sqlalchemy.update(self._table)
                .where(self._table.c.id == record_id)
                .values(**instance.model_dump())
            )
            return result.rowcount == 1

    async def delete(self, record_id: int) -> bool:
        """Delete a row by id; True if it existed."""
        async with self._database.begin() as conn:
            result = await conn.execute(
                sqlalchemy.delete(self._table).where(self._table.c.id == record_id)
            )
            return result.rowcount == 1


class Database:
    """Owns the engine, the schema metadata, and one Repository per model."""

    def __init__(
        self, url: str, models: typing.Sequence[type[pydantic.BaseModel]]
    ) -> None:
        self._engine = sa_async.create_async_engine(url)
        self._metadata = sqlalchemy.MetaData()
        self._repos = {
            model: Repository(model, table_for(model, self._metadata), self)
            for model in models
        }
        self._ready = False
        self._ready_lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def connect(
        self,
    ) -> typing.AsyncIterator[sa_async.AsyncConnection]:
        """A read connection, lazily initializing the schema on first use."""
        await self.ensure_ready()
        async with self._engine.connect() as conn:
            yield conn

    @contextlib.asynccontextmanager
    async def begin(self) -> typing.AsyncIterator[sa_async.AsyncConnection]:
        """A transactional connection, lazily initializing the schema on first use."""
        await self.ensure_ready()
        async with self._engine.begin() as conn:
            yield conn

    def repo(self, model: type[pydantic.BaseModel]) -> Repository:
        try:
            return self._repos[model]
        except KeyError:
            raise KeyError(
                f"{model.__name__} is not registered with this Database"
            ) from None

    async def create_all(self) -> None:
        """Create any missing tables. (No migrations in v0.1: existing tables
        are left untouched even if the model changed — drop and recreate.)"""
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all)

    async def ensure_ready(self) -> None:
        """Idempotent first-use init, safe under concurrent requests.

        Enforced at connection acquisition (connect/begin) rather than via
        HTTP middleware or startup hooks: mounted sub-apps get no lifespan
        events from Starlette hosts, and the in-process query API never
        passes through HTTP at all. After init this is one bool check.
        """
        if self._ready:
            return
        async with self._ready_lock:
            if not self._ready:
                await self.create_all()
                self._ready = True

    async def dispose(self) -> None:
        await self._engine.dispose()
