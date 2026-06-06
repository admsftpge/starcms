"""Tests for the in-process Python query face (cms.get/find/create).

Every test here runs against an unmounted cms: the face involves no HTTP
machinery at all — that's its point.
"""

import pydantic
import pytest

import sample_models
import starcms


class TestQueryFace:
    async def test_create_then_get_round_trips(self, cms):
        record_id = await cms.create(sample_models.Article(title="Hello"))

        row = await cms.get(sample_models.Article, record_id)
        assert row is not None
        assert row["title"] == "Hello"
        assert row["id"] == record_id

    async def test_get_missing_returns_none(self, cms):
        assert await cms.get(sample_models.Article, 999) is None

    async def test_find_filters_by_field_equality(self, cms):
        await cms.create(sample_models.Article(title="draft"))
        await cms.create(sample_models.Article(title="live", published=True))

        rows = await cms.find(sample_models.Article, published=True)
        assert [r["title"] for r in rows] == ["live"]

    async def test_find_unfiltered_returns_all_with_paging(self, cms):
        for title in ["a", "b", "c"]:
            await cms.create(sample_models.Article(title=title))

        assert len(await cms.find(sample_models.Article)) == 3
        page = await cms.find(sample_models.Article, limit=1, offset=1)
        assert [r["title"] for r in page] == ["b"]

    async def test_find_rejects_unknown_filter_fields(self, cms):
        with pytest.raises(ValueError, match="no field"):
            await cms.find(sample_models.Article, bogus=1)

    async def test_where_dict_escapes_reserved_parameter_names(self, cms):
        # Sugar kwargs collide with limit/offset/where; the dict never does.
        await cms.create(sample_models.Article(title="live", published=True))

        rows = await cms.find(sample_models.Article, where={"published": True})
        assert [r["title"] for r in rows] == ["live"]


class TestModelRegistry:
    def test_models_sharing_a_key_are_rejected_at_construction(self, db_url):
        class Article(pydantic.BaseModel):  # same key as sample_models.Article
            title: str

        with pytest.raises(ValueError, match="'article'"):
            starcms.StarCMS(db=db_url, models=[sample_models.Article, Article])
