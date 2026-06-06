"""The admin sub-application: a self-contained Starlette app.

Built on raw Starlette — the shared foundation of FastAPI and FastHTML — so
one sub-app mounts identically into either host, and starcms never depends
on either framework. HTML is generated with htpy (which escapes all content,
so stored values can't inject markup). Forms are classic POST + redirect:
no JavaScript is involved anywhere yet. Form machinery lives in forms.py.
"""

import typing

import htpy
import pydantic
from starlette import applications, exceptions, middleware, requests, responses, routing
from starlette.middleware import sessions

from starcms import auth, forms, schema

if typing.TYPE_CHECKING:
    from starcms import core


def _model_or_404(cms: "core.StarCMS", slug: str) -> type[pydantic.BaseModel]:
    for model in cms.models:
        if schema.model_key(model) == slug:
            return model
    raise exceptions.HTTPException(status_code=404, detail=f"No model {slug!r}")


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


# --- views ---------------------------------------------------------------


def _redirect_to_list(
    request: requests.Request, slug: str
) -> responses.RedirectResponse:
    """The post-mutation destination: 303 back to the model's list."""
    return responses.RedirectResponse(
        request.url_for("model_list", slug=slug), status_code=303
    )


async def login(request: requests.Request) -> responses.Response:
    action = str(request.url_for("login"))
    if request.method == "GET":
        return responses.HTMLResponse(_layout("Log in", forms.login_form(action)))

    await auth.require_csrf(request)
    form = await request.form()
    if auth.verify(str(form.get("username", "")), str(form.get("password", ""))):
        request.session["user"] = str(form.get("username"))
        return responses.RedirectResponse(
            request.url_for("home"), status_code=303
        )
    return responses.HTMLResponse(
        _layout("Log in", forms.login_form(action, error="Invalid credentials.")),
        status_code=401,
    )


async def logout(request: requests.Request) -> responses.Response:
    await auth.require_csrf(request)
    request.session.clear()
    return responses.RedirectResponse(request.url_for("login"), status_code=303)


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
            forms.post_form(
                str(request.url_for("logout")),
                htpy.button(type="submit")["Log out"],
            ),
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
            spec.name: forms.to_form_value(spec, spec.resolve_default())
            for spec in specs
        }
        return responses.HTMLResponse(
            _layout(title, forms.model_form(specs, values, {}, action))
        )

    await auth.require_csrf(request)
    form = await request.form()
    instance, errors, raw = forms.parse_form(model, form)
    if instance is None:
        # Re-render with the user's input preserved and errors inline.
        return responses.HTMLResponse(
            _layout(title, forms.model_form(specs, raw, errors, action)),
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
            spec.name: forms.to_form_value(spec, row[spec.name])
            for spec in specs
        }
        return responses.HTMLResponse(
            _layout(
                title,
                forms.model_form(specs, values, {}, action),
                forms.delete_form(delete_action),
            )
        )

    await auth.require_csrf(request)
    form = await request.form()
    instance, errors, raw = forms.parse_form(model, form)
    if instance is None:
        # Same page composition as GET: the Delete button must not vanish
        # just because a save attempt failed.
        return responses.HTMLResponse(
            _layout(
                title,
                forms.model_form(specs, raw, errors, action),
                forms.delete_form(delete_action),
            ),
            status_code=422,
        )
    if not await repo.update(record_id, instance):
        raise exceptions.HTTPException(status_code=404)
    return _redirect_to_list(request, slug)


async def model_delete(request: requests.Request) -> responses.Response:
    await auth.require_csrf(request)
    cms = request.app.state.cms
    model = _model_or_404(cms, request.path_params["slug"])
    slug = schema.model_key(model)
    if not await cms.database.repo(model).delete(request.path_params["record_id"]):
        raise exceptions.HTTPException(status_code=404)
    return _redirect_to_list(request, slug)


# --- app -----------------------------------------------------------------


def build_app(
    cms: "core.StarCMS", mount_path: str = "/admin"
) -> applications.Starlette:
    """Build the admin app for one StarCMS instance.

    The instance travels on app.state rather than in closures, so handlers
    can move to their own modules as the admin grows. Database readiness
    needs no middleware here: the Database itself initializes lazily on
    first connection. mount_path scopes the session cookie to the admin —
    note it's the within-host path, so a reverse proxy adding its own
    prefix needs the cookie path reconsidered (known v0.1 limitation).
    """
    app = applications.Starlette(
        routes=[
            routing.Route("/", home, name="home"),
            routing.Route(
                "/login", login, methods=["GET", "POST"], name="login"
            ),
            routing.Route("/logout", logout, methods=["POST"], name="logout"),
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
            # Keep the wildcard last: anything above it (e.g. /login)
            # would otherwise be swallowed as a model slug.
            routing.Route("/{slug}", model_list, name="model_list"),
        ],
        middleware=[
            # Session first (outermost) so the gate can read it. The cookie
            # is named and path-scoped so it can never collide with the
            # host app's own session (e.g. FastHTML's default 'session').
            middleware.Middleware(
                sessions.SessionMiddleware,
                secret_key=auth.session_secret(),
                session_cookie="starcms_session",
                path=mount_path,
                same_site="lax",
            ),
            middleware.Middleware(auth.AuthGate),
        ],
    )
    app.state.cms = cms
    return app
