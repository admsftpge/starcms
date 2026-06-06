"""Tests for the persistence layer (db.py)."""

import datetime

import pydantic
import pytest
import sqlalchemy

import sample_models
from starcms import db


class TestTableGeneration:
    def table(self) -> sqlalchemy.Table:
        return db.table_for(sample_models.Article, sqlalchemy.MetaData())

    def test_table_name_is_lowercased_model_name(self):
        assert self.table().name == "article"

    def test_id_primary_key_is_added(self):
        id_col = self.table().c.id
        assert id_col.primary_key is True
        assert isinstance(id_col.type, sqlalchemy.Integer)

    def test_column_types_follow_field_specs(self):
        cols = self.table().c
        assert isinstance(cols.title.type, sqlalchemy.Text)
        assert isinstance(cols.views.type, sqlalchemy.Integer)
        assert isinstance(cols.rating.type, sqlalchemy.Float)
        assert isinstance(cols.published.type, sqlalchemy.Boolean)
        assert isinstance(cols.published_at.type, sqlalchemy.DateTime)

    def test_nullability_follows_field_specs(self):
        cols = self.table().c
        assert cols.title.nullable is False
        assert cols.body.nullable is True


class TestCrud:
    async def test_create_returns_sequential_ids(self, repo):
        assert await repo.create(sample_models.Article(title="first")) == 1
        assert await repo.create(sample_models.Article(title="second")) == 2

    async def test_create_then_get_round_trips_all_types(self, repo):
        when = datetime.datetime(2026, 6, 5, 12, 30)
        article = sample_models.Article(
            title="Hello",
            body=None,
            views=42,
            rating=4.5,
            published=True,
            published_at=when,
        )
        record_id = await repo.create(article)

        row = await repo.get(record_id)
        assert row == {
            "id": record_id,
            "title": "Hello",
            "body": None,
            "views": 42,
            "rating": 4.5,
            "published": True,
            "published_at": when,
        }

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(999) is None

    async def test_list_returns_rows_in_id_order(self, repo):
        await repo.create(sample_models.Article(title="a"))
        await repo.create(sample_models.Article(title="b"))

        rows = await repo.list()
        assert [r["title"] for r in rows] == ["a", "b"]
        assert [r["id"] for r in rows] == [1, 2]

    async def test_list_respects_limit_and_offset(self, repo):
        for title in ["a", "b", "c", "d"]:
            await repo.create(sample_models.Article(title=title))

        page = await repo.list(limit=2, offset=1)
        assert [r["title"] for r in page] == ["b", "c"]

    async def test_list_where_filters_by_equality(self, repo):
        await repo.create(sample_models.Article(title="draft"))
        await repo.create(sample_models.Article(title="live", published=True))

        rows = await repo.list(where={"published": True})
        assert [r["title"] for r in rows] == ["live"]
        assert await repo.list(where={"title": "nope"}) == []

    async def test_list_where_rejects_unknown_fields(self, repo):
        with pytest.raises(ValueError, match="no field 'bogus'"):
            await repo.list(where={"bogus": 1})

    async def test_update_replaces_fields(self, repo):
        record_id = await repo.create(sample_models.Article(title="before"))

        updated = await repo.update(
            record_id, sample_models.Article(title="after", views=7)
        )
        assert updated is True
        row = await repo.get(record_id)
        assert row["title"] == "after"
        assert row["views"] == 7

    async def test_update_missing_returns_false(self, repo):
        assert await repo.update(999, sample_models.Article(title="x")) is False

    async def test_delete_removes_row(self, repo):
        record_id = await repo.create(sample_models.Article(title="doomed"))

        assert await repo.delete(record_id) is True
        assert await repo.get(record_id) is None

    async def test_delete_missing_returns_false(self, repo):
        assert await repo.delete(999) is False

    async def test_writes_reject_foreign_instances(self, repo):
        class Impostor(pydantic.BaseModel):
            title: str

        with pytest.raises(TypeError, match="Article instance"):
            await repo.create(Impostor(title="sneaky"))

    async def test_unregistered_model_has_no_repo(self, database):
        class Unregistered(pydantic.BaseModel):
            title: str

        with pytest.raises(KeyError, match="Unregistered"):
            database.repo(Unregistered)

    async def test_schema_initializes_lazily_on_first_operation(self, db_url):
        # No create_all: connection acquisition must init the schema itself.
        # This is what guarantees readiness for ALL consumers — admin, API,
        # and in-process queries alike — with no middleware involved.
        d = db.Database(db_url, [sample_models.Article])
        try:
            assert await d.repo(sample_models.Article).list() == []
        finally:
            await d.dispose()
