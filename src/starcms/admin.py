"""The admin sub-application: a self-contained Starlette app.

Built on raw Starlette — the shared foundation of FastAPI and FastHTML — so
one sub-app mounts identically into either host, and starcms never depends
on either framework. HTML is generated with htpy (which escapes all content,
so stored values can't inject markup). Forms are classic POST + redirect:
no JavaScript is involved anywhere yet.
"""

import datetime
import typing

import htpy
import pydantic
from starlette import applications, exceptions, requests, responses, routing

from starcms import schema

if typing.TYPE_CHECKING:
    from starcms import core


def _model_or_404(cms: "core.StarCMS", slug: str) -> type[pydantic.BaseModel]:
    for model in cms.models:
        if schema.model_key(model) == slug:
            return model
    raise exceptions.HTTPException(status_code=404, detail=f"No model {slug!r}")


# --- widgets -------------------------------------------------------------

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


def _to_form_value(spec: schema.FieldSpec, value: typing.Any) -> FormValue:
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


def _post_form(action: str, *children: htpy.Node) -> htpy.Node:
    """Every admin mutation posts through here — the one place a CSRF
    token gets injected when auth lands."""
    return htpy.form(method="post", action=action)[children]


def _model_form(
    specs: tuple[schema.FieldSpec, ...],
    values: dict[str, FormValue],
    errors: dict[str, str],
    action: str,
) -> htpy.Node:
    return _post_form(
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


# --- form parsing (the way back in) --------------------------------------


def _parse_form(
    model: type[pydantic.BaseModel], form: typing.Mapping[str, typing.Any]
) -> tuple[pydantic.BaseModel | None, dict[str, str], dict[str, FormValue]]:
    """Browser form data (all strings) → validated instance, or field errors.

    Returns (instance, errors, raw): exactly one of instance/errors is
    populated; raw holds what the user typed, for error re-rendering.
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


# --- components ----------------------------------------------------------


def _layout(title: str, *content: htpy.Node) -> str:
    return str(
        htpy.html[
            htpy.head[htpy.title[f"{title} — starcms"]],
            htpy.body[htpy.h1[title], content],
        ]
    )


def _cell(value: typing.Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "✓"
    if value is False:
        return "✗"
    return str(value)


def _record_table(
    specs: tuple[schema.FieldSpec, ...],
    rows: list[dict],
    edit_url: typing.Callable[[int], str],
) -> htpy.Node:
    if not rows:
        return htpy.p["Nothing here yet."]
    return htpy.table[
        htpy.thead[
            htpy.tr[htpy.th["id"], (htpy.th[s.label] for s in specs)]
        ],
        htpy.tbody[
            (
                htpy.tr[
                    htpy.td[
                        htpy.a(href=edit_url(row[schema.ID_FIELD]))[
                            row[schema.ID_FIELD]
                        ]
                    ],
                    (htpy.td[_cell(row[s.name])] for s in specs),
                ]
                for row in rows
            )
        ],
    ]


def _delete_form(action: str) -> htpy.Node:
    # Deliberately lives only on the edit page: reaching it means you are
    # looking at exactly the record you are about to delete — the no-JS
    # stand-in for a confirmation dialog until htmx arrives.
    return _post_form(action, htpy.button(type="submit")["Delete"])


# --- views ---------------------------------------------------------------


def _redirect_to_list(
    request: requests.Request, slug: str
) -> responses.RedirectResponse:
    """The post-mutation destination: 303 back to the model's list."""
    return responses.RedirectResponse(
        request.url_for("model_list", slug=slug), status_code=303
    )


async def home(request: requests.Request) -> responses.HTMLResponse:
    cms = request.app.state.cms
    return responses.HTMLResponse(
        _layout(
            "starcms admin",
            htpy.ul[
                (
                    htpy.li[
                        htpy.a(
                            href=str(
                                request.url_for(
                                    "model_list", slug=schema.model_key(model)
                                )
                            )
                        )[model.__name__]
                    ]
                    for model in cms.models
                )
            ],
        )
    )


async def model_list(request: requests.Request) -> responses.HTMLResponse:
    cms = request.app.state.cms
    model = _model_or_404(cms, request.path_params["slug"])
    slug = schema.model_key(model)
    specs = schema.introspect(model)
    rows = await cms.database.repo(model).list()
    return responses.HTMLResponse(
        _layout(
            model.__name__,
            htpy.p[
                htpy.a(href=str(request.url_for("home")))["← all models"],
                " · ",
                htpy.a(href=str(request.url_for("model_create", slug=slug)))[
                    f"+ New {model.__name__}"
                ],
            ],
            _record_table(
                specs,
                rows,
                edit_url=lambda record_id: str(
                    request.url_for("model_edit", slug=slug, record_id=record_id)
                ),
            ),
        )
    )


async def model_create(request: requests.Request) -> responses.Response:
    cms = request.app.state.cms
    model = _model_or_404(cms, request.path_params["slug"])
    slug = schema.model_key(model)
    specs = schema.introspect(model)
    action = str(request.url_for("model_create", slug=slug))
    title = f"New {model.__name__}"

    if request.method == "GET":
        values = {
            spec.name: _to_form_value(spec, spec.resolve_default())
            for spec in specs
        }
        return responses.HTMLResponse(
            _layout(title, _model_form(specs, values, {}, action))
        )

    form = await request.form()
    instance, errors, raw = _parse_form(model, form)
    if instance is None:
        # Re-render with the user's input preserved and errors inline.
        return responses.HTMLResponse(
            _layout(title, _model_form(specs, raw, errors, action)),
            status_code=422,
        )
    await cms.database.repo(model).create(instance)
    return _redirect_to_list(request, slug)


async def model_edit(request: requests.Request) -> responses.Response:
    cms = request.app.state.cms
    model = _model_or_404(cms, request.path_params["slug"])
    slug = schema.model_key(model)
    record_id = request.path_params["record_id"]
    specs = schema.introspect(model)
    repo = cms.database.repo(model)
    action = str(request.url_for("model_edit", slug=slug, record_id=record_id))
    delete_action = str(
        request.url_for("model_delete", slug=slug, record_id=record_id)
    )
    title = f"Edit {model.__name__} #{record_id}"

    if request.method == "GET":
        row = await repo.get(record_id)
        if row is None:
            raise exceptions.HTTPException(status_code=404)
        values = {
            spec.name: _to_form_value(spec, row[spec.name]) for spec in specs
        }
        return responses.HTMLResponse(
            _layout(
                title,
                _model_form(specs, values, {}, action),
                _delete_form(delete_action),
            )
        )

    form = await request.form()
    instance, errors, raw = _parse_form(model, form)
    if instance is None:
        # Same page composition as GET: the Delete button must not vanish
        # just because a save attempt failed.
        return responses.HTMLResponse(
            _layout(
                title,
                _model_form(specs, raw, errors, action),
                _delete_form(delete_action),
            ),
            status_code=422,
        )
    if not await repo.update(record_id, instance):
        raise exceptions.HTTPException(status_code=404)
    return _redirect_to_list(request, slug)


async def model_delete(request: requests.Request) -> responses.Response:
    cms = request.app.state.cms
    model = _model_or_404(cms, request.path_params["slug"])
    slug = schema.model_key(model)
    if not await cms.database.repo(model).delete(request.path_params["record_id"]):
        raise exceptions.HTTPException(status_code=404)
    return _redirect_to_list(request, slug)


# --- app -----------------------------------------------------------------


def build_app(cms: "core.StarCMS") -> applications.Starlette:
    """Build the admin app for one StarCMS instance.

    The instance travels on app.state rather than in closures, so handlers
    can move to their own modules as the admin grows. Database readiness
    needs no middleware here: the Database itself initializes lazily on
    first connection.
    """
    app = applications.Starlette(
        routes=[
            routing.Route("/", home, name="home"),
            routing.Route(
                "/{slug}/new", model_create, methods=["GET", "POST"],
                name="model_create",
            ),
            routing.Route(
                "/{slug}/{record_id:int}/edit", model_edit,
                methods=["GET", "POST"], name="model_edit",
            ),
            routing.Route(
                "/{slug}/{record_id:int}/delete", model_delete,
                methods=["POST"], name="model_delete",
            ),
            routing.Route("/{slug}", model_list, name="model_list"),
        ],
    )
    app.state.cms = cms
    return app
