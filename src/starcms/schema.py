"""Introspection layer: read a Pydantic model, emit FieldSpecs.

The FieldSpec is starcms's single source of truth. Every downstream layer
(database columns, form widgets, table columns, API schemas) is generated
from FieldSpecs — never from the Pydantic model directly. That keeps type
mapping decisions in exactly one place.
"""

import dataclasses
import datetime
import functools
import types
import typing

import pydantic

# Types starcms knows how to store and render in v0.1. Anything else is
# rejected loudly at introspection time rather than failing later in the
# admin or the database layer.
SUPPORTED_TYPES: tuple[type, ...] = (str, int, float, bool, datetime.datetime)

# Field name reserved for the system-managed primary key. Defined here, not
# in the db layer, because every layer references it: db columns, admin
# routes (/{id}), API serialization — and the rejection must happen at
# introspection time like every other model-shape rule.
ID_FIELD: typing.Final = "id"


class UnsupportedTypeError(TypeError):
    """Raised when a model field's type has no starcms mapping."""


class _MissingType:
    def __repr__(self) -> str:
        return "MISSING"


# Sentinel for "no default exists" — distinct from a real default of None.
MISSING: typing.Final = _MissingType()


@dataclasses.dataclass(frozen=True, slots=True)
class FieldSpec:
    """A neutral description of one model field.

    Attributes:
        name: the field's attribute name on the model.
        python_type: the underlying type with any Optional wrapper removed.
        label: human-facing name for forms and table headers.
        required: True if the user must supply a value (no default exists).
        nullable: True if the field accepts None (was Optional[...]).
        default: the field's static default, or MISSING if there isn't one.
        default_factory: zero-arg callable producing a fresh default, if the
            model declared one. Kept as a callable — not resolved here — so
            consumers get a live value per use (e.g. datetime.now stamps row
            creation time, not app startup time).
    """

    name: str
    python_type: type
    label: str
    required: bool
    nullable: bool
    default: typing.Any = MISSING
    default_factory: typing.Callable[[], typing.Any] | None = None

    @property
    def has_default(self) -> bool:
        return self.default is not MISSING or self.default_factory is not None

    def resolve_default(self) -> typing.Any:
        """Produce the default value (calling any factory fresh), or MISSING."""
        if self.default_factory is not None:
            return self.default_factory()
        return self.default


def _unwrap_optional(annotation: typing.Any) -> tuple[typing.Any, bool]:
    """Strip Optional[...] / X | None, returning (inner_type, nullable).

    Unions other than "one type | None" are not supported and are returned
    as-is for the caller to reject.
    """
    origin = typing.get_origin(annotation)
    # typing.Union covers Optional[X]; types.UnionType covers X | None syntax.
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def introspect(model: type[pydantic.BaseModel]) -> tuple[FieldSpec, ...]:
    """Read a Pydantic model class and return one FieldSpec per field.

    Results are cached per model class: downstream layers (db, forms, API)
    may call this freely without re-paying introspection.

    Raises:
        TypeError: if `model` is not a Pydantic BaseModel subclass.
        ValueError: if the model declares the reserved field name "id".
        UnsupportedTypeError: if any field's type has no starcms mapping.
    """
    # Validate before the cache: functools.cache would otherwise greet bad
    # inputs (e.g. unhashable model instances) with its own TypeError.
    if not (isinstance(model, type) and issubclass(model, pydantic.BaseModel)):
        raise TypeError(
            f"introspect() expects a Pydantic BaseModel subclass, got {model!r}"
        )
    return _introspect(model)


@functools.cache
def _introspect(model: type[pydantic.BaseModel]) -> tuple[FieldSpec, ...]:
    specs: list[FieldSpec] = []
    for name, info in model.model_fields.items():
        if name == ID_FIELD:
            raise ValueError(
                f"{model.__name__} declares a field named {ID_FIELD!r}; starcms "
                "manages the primary key itself, so models must not define one."
            )

        annotation, nullable = _unwrap_optional(info.annotation)

        # Exact match only: bool is a subclass of int, so issubclass checks
        # would silently misfile types into the wrong column/widget.
        if annotation not in SUPPORTED_TYPES:
            supported = ", ".join(t.__name__ for t in SUPPORTED_TYPES)
            raise UnsupportedTypeError(
                f"{model.__name__}.{name}: unsupported type {info.annotation!r}. "
                f"starcms supports: {supported} (each optionally wrapped in Optional)."
            )

        if info.default_factory is not None:
            default, factory = MISSING, info.default_factory
        elif info.is_required():
            default, factory = MISSING, None
        else:
            default, factory = info.default, None

        specs.append(
            FieldSpec(
                name=name,
                python_type=annotation,
                label=info.title or name.replace("_", " ").capitalize(),
                required=info.is_required(),
                nullable=nullable,
                default=default,
                default_factory=factory,
            )
        )
    return tuple(specs)
