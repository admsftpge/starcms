"""The admin sub-application: a self-contained Starlette app.

Built on raw Starlette — the shared foundation of FastAPI and FastHTML — so
one sub-app mounts identically into either host, and starcms never depends
on either framework. HTML is generated with htpy (which escapes all content,
so stored values can't inject markup).
"""

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


# --- components ---------------------------------------------------------


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
    specs: tuple[schema.FieldSpec, ...], rows: list[dict]
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
                    htpy.td[row[schema.ID_FIELD]],
                    (htpy.td[_cell(row[s.name])] for s in specs),
                ]
                for row in rows
            )
        ],
    ]


# --- views ---------------------------------------------------------------


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
    specs = schema.introspect(model)
    rows = await cms.database.repo(model).list()
    return responses.HTMLResponse(
        _layout(
            model.__name__,
            htpy.p[htpy.a(href=str(request.url_for("home")))["← all models"]],
            _record_table(specs, rows),
        )
    )


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
            routing.Route("/{slug}", model_list, name="model_list"),
        ],
    )
    app.state.cms = cms
    return app
