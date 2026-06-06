"""Form machinery: FieldSpecs → widgets/forms, and browser data → instances.

Both directions live in one module so the round-trip stays in sync: the
widget map decides what the browser will send, and the parser decides how
it is read back.

Placement rule: every form that POSTs is built here (including non-model
forms like delete and the future login), so post_form stays the single
point where a CSRF token gets injected.
"""

import datetime
import typing

import htpy
import pydantic

from starcms import schema

# FieldSpec.python_type → <input type=...>. bool is handled separately:
# checkboxes have structurally different semantics (absent when unchecked).
_INPUT_TYPES: dict[type, str] = {
    str: "text",
    int: "number",
    float: "number",
    datetime.datetime: "datetime-local",
}

# Same import-time drift guard as db._COLUMN_TYPES: every supported type
# must have a widget decision, here, not at render time.
assert set(_INPUT_TYPES) | {bool} == set(schema.SUPPORTED_TYPES)

# What the browser sends/shows: text fields carry strings, checkboxes bools.
FormValue = str | bool


def to_form_value(spec: schema.FieldSpec, value: typing.Any) -> FormValue:
    """Typed Python value (spec default or stored row) → what its input expects."""
    if spec.python_type is bool:
        return value is True
    if value is None or value is schema.MISSING:
        return ""
    if isinstance(value, datetime.datetime):
        # Keep seconds: an edit-form resave must not silently truncate
        # stored values to the minute.
        return value.isoformat(timespec="seconds")
    return str(value)


def _field_widget(spec: schema.FieldSpec, value: FormValue) -> htpy.Node:
    if spec.python_type is bool:
        return htpy.input(
            type="checkbox", name=spec.name, id=f"field-{spec.name}",
            checked=value is True,
        )
    if spec.python_type is float:
        step = "any"
    elif spec.python_type is datetime.datetime:
        step = "1"  # lets datetime-local carry seconds
    else:
        step = None
    return htpy.input(
        type=_INPUT_TYPES[spec.python_type],
        name=spec.name,
        id=f"field-{spec.name}",
        value=typing.cast(str, value),
        # HTML-required only when empty would be rejected anyway: a nullable
        # field accepts None, so empty is a legitimate submission for it.
        required=spec.required and not spec.nullable,
        step=step,
    )


def post_form(action: str, *children: htpy.Node) -> htpy.Node:
    """Every admin mutation posts through here — the one place a CSRF
    token gets injected when auth lands.

    Transport decision (so auth doesn't relitigate it): the token will
    arrive ambiently via a contextvar set by the auth middleware, not as
    a parameter — parameter-threading would ripple through every form
    builder and view, and forms.py must stay free of request handling.
    """
    return htpy.form(method="post", action=action)[children]


def model_form(
    specs: tuple[schema.FieldSpec, ...],
    values: dict[str, FormValue],
    errors: dict[str, str],
    action: str,
) -> htpy.Node:
    return post_form(
        action,
        # Model-level validator errors arrive with an empty loc -> key "".
        htpy.p(".error")[errors[""]] if "" in errors else None,
        (
            htpy.p[
                htpy.label(for_=f"field-{spec.name}")[spec.label],
                " ",
                _field_widget(spec, values.get(spec.name, "")),
                htpy.span(".error")[f" {errors[spec.name]}"]
                if spec.name in errors
                else None,
            ]
            for spec in specs
        ),
        htpy.button(type="submit")["Save"],
    )


def delete_form(action: str) -> htpy.Node:
    # Deliberately lives only on the edit page: reaching it means you are
    # looking at exactly the record you are about to delete — the no-JS
    # stand-in for a confirmation dialog until htmx arrives.
    return post_form(action, htpy.button(type="submit")["Delete"])


def parse_form(
    model: type[pydantic.BaseModel], form: typing.Mapping[str, typing.Any]
) -> tuple[pydantic.BaseModel | None, dict[str, str], dict[str, FormValue]]:
    """Browser form data (all strings) → validated instance, or field errors.

    Returns (instance, errors, raw): exactly one of instance/errors is
    populated; raw holds what the user typed, for error re-rendering.

    Browser form data ONLY: the coercions here (empty string → None,
    checkbox-absence → False) would mangle typed JSON — the API layer
    validates payloads with model_validate directly, never through this.
    """
    raw: dict[str, FormValue] = {}
    values: dict[str, typing.Any] = {}
    for spec in schema.introspect(model):
        if spec.python_type is bool:
            # Unchecked checkboxes are simply absent from the submission.
            checked = spec.name in form
            raw[spec.name] = checked
            values[spec.name] = checked
            continue

        text = str(form.get(spec.name, ""))
        raw[spec.name] = text
        if text == "":
            if spec.nullable:
                values[spec.name] = None
            # Not nullable: omit the key — Pydantic fills the default or
            # reports "Field required", both of which are what we want.
            continue
        # Pass the string through: Pydantic coerces "42", "1.5", ISO dates.
        values[spec.name] = text

    try:
        return model.model_validate(values), {}, raw
    except pydantic.ValidationError as exc:
        errors = {
            ".".join(str(part) for part in err["loc"]): err["msg"]
            for err in exc.errors()
        }
        return None, errors, raw
