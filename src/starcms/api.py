"""The JSON content API: read-only delivery of stored content.

A second, separate sub-app rather than routes on the admin: content
delivery is public-ish while the admin is private, so they get different
perimeters — the API carries no session, no login, no CSRF. Read-only in
v0.1 (writes go through the admin). There is no built-in API auth: front
it with your own middleware if your content isn't public.

Contract notes: collection responses are enveloped ({"items": [...]}) so
pagination metadata can arrive later without breaking consumers, and they
are paged by default — a public endpoint must never return an unbounded
table.
"""

import typing

import pydantic_core
from starlette import applications, requests, responses, routing

if typing.TYPE_CHECKING:
    from starcms import core

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _not_found() -> responses.JSONResponse:
    return responses.JSONResponse({"detail": "Not found"}, status_code=404)


async def collection(request: requests.Request) -> responses.JSONResponse:
    cms = request.app.state.cms
    model = cms.model_by_key(request.path_params["slug"])
    if model is None:
        return _not_found()

    params = request.query_params
    try:
        requested = int(params["limit"]) if "limit" in params else DEFAULT_PAGE_SIZE
        offset = max(0, int(params.get("offset", 0)))
    except ValueError:
        return responses.JSONResponse(
            {"detail": "limit and offset must be integers"}, status_code=400
        )
    limit = max(1, min(requested, MAX_PAGE_SIZE))

    rows = await cms.database.repo(model).list(limit=limit, offset=offset)
    return responses.JSONResponse(
        {"items": pydantic_core.to_jsonable_python(rows)}
    )


async def item(request: requests.Request) -> responses.JSONResponse:
    cms = request.app.state.cms
    model = cms.model_by_key(request.path_params["slug"])
    if model is None:
        return _not_found()

    row = await cms.database.repo(model).get(request.path_params["record_id"])
    if row is None:
        return _not_found()
    return responses.JSONResponse(pydantic_core.to_jsonable_python(row))


def build_app(cms: "core.StarCMS") -> applications.Starlette:
    """Build the content API app for one StarCMS instance."""
    app = applications.Starlette(
        routes=[
            routing.Route("/{slug}", collection, name="collection"),
            routing.Route("/{slug}/{record_id:int}", item, name="item"),
        ],
    )
    app.state.cms = cms
    return app
