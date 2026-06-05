"""Tests for the introspection layer (schema.py)."""

import datetime
import typing

import pydantic
import pytest

from starcms import schema


class BlogPost(pydantic.BaseModel):
    title: str
    view_count: int
    rating: float
    published: bool
    created_at: datetime.datetime


def spec_for(model: type[pydantic.BaseModel], name: str) -> schema.FieldSpec:
    return next(s for s in schema.introspect(model) if s.name == name)


class TestBasicIntrospection:
    def test_one_spec_per_field_in_declaration_order(self):
        specs = schema.introspect(BlogPost)
        assert [s.name for s in specs] == [
            "title",
            "view_count",
            "rating",
            "published",
            "created_at",
        ]

    def test_python_types_are_unwrapped_exactly(self):
        specs = {s.name: s.python_type for s in schema.introspect(BlogPost)}
        assert specs == {
            "title": str,
            "view_count": int,
            "rating": float,
            "published": bool,
            "created_at": datetime.datetime,
        }

    def test_fields_without_defaults_are_required(self):
        for spec in schema.introspect(BlogPost):
            assert spec.required is True
            assert spec.has_default is False

    def test_results_are_cached_per_model(self):
        assert schema.introspect(BlogPost) is schema.introspect(BlogPost)


class TestOptionalAndDefaults:
    def test_optional_unwraps_to_inner_type_and_nullable(self):
        class M(pydantic.BaseModel):
            subtitle: str | None

        spec = spec_for(M, "subtitle")
        assert spec.python_type is str
        assert spec.nullable is True
        assert spec.required is True  # Optional without default still needs a value

    def test_typing_optional_spelling_also_unwraps(self):
        class M(pydantic.BaseModel):
            subtitle: typing.Optional[str]  # noqa: UP045 — old spelling on purpose

        spec = spec_for(M, "subtitle")
        assert spec.python_type is str
        assert spec.nullable is True

    def test_default_value_makes_field_not_required(self):
        class M(pydantic.BaseModel):
            published: bool = False

        spec = spec_for(M, "published")
        assert spec.required is False
        assert spec.has_default is True
        assert spec.default is False

    def test_no_default_is_distinguishable_from_none_default(self):
        class M(pydantic.BaseModel):
            title: str
            subtitle: str | None = None

        assert spec_for(M, "title").default is schema.MISSING
        assert spec_for(M, "title").has_default is False
        assert spec_for(M, "subtitle").default is None
        assert spec_for(M, "subtitle").has_default is True

    def test_default_factory_is_kept_live_not_frozen(self):
        calls = []

        def factory() -> str:
            calls.append(1)
            return f"call-{len(calls)}"

        class M(pydantic.BaseModel):
            tags: str = pydantic.Field(default_factory=factory)

        spec = spec_for(M, "tags")
        assert spec.required is False
        assert spec.has_default is True
        assert spec.default is schema.MISSING  # the factory, not a frozen value
        # Each resolution calls the factory fresh — a datetime.now default
        # must stamp row-creation time, not introspection time.
        assert spec.resolve_default() == "call-1"
        assert spec.resolve_default() == "call-2"

    def test_resolve_default_without_any_default_returns_missing(self):
        assert spec_for(BlogPost, "title").resolve_default() is schema.MISSING


class TestLabels:
    def test_label_defaults_to_humanized_field_name(self):
        class M(pydantic.BaseModel):
            view_count: int

        assert spec_for(M, "view_count").label == "View count"

    def test_explicit_field_title_wins(self):
        class M(pydantic.BaseModel):
            view_count: int = pydantic.Field(title="Views")

        assert spec_for(M, "view_count").label == "Views"


class TestRejections:
    def test_non_model_class_is_rejected(self):
        class Plain:
            title: str

        with pytest.raises(TypeError, match="BaseModel subclass"):
            schema.introspect(Plain)  # type: ignore[arg-type]

    def test_model_instance_is_rejected(self):
        post = BlogPost(
            title="t",
            view_count=0,
            rating=0.0,
            published=False,
            created_at=datetime.datetime(2026, 1, 1),
        )
        with pytest.raises(TypeError, match="BaseModel subclass"):
            schema.introspect(post)  # type: ignore[arg-type]

    def test_unsupported_type_is_rejected_with_field_context(self):
        class M(pydantic.BaseModel):
            data: dict

        with pytest.raises(schema.UnsupportedTypeError, match="M.data"):
            schema.introspect(M)

    def test_multi_type_union_is_rejected(self):
        class M(pydantic.BaseModel):
            value: int | str

        with pytest.raises(schema.UnsupportedTypeError, match="M.value"):
            schema.introspect(M)

    def test_bool_is_not_misfiled_as_int(self):
        # bool subclasses int in Python; exact-match type checks must keep
        # them distinct or checkboxes would render as number inputs.
        class M(pydantic.BaseModel):
            flag: bool

        assert spec_for(M, "flag").python_type is bool
