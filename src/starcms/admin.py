"""The admin sub-application: a self-contained Starlette app.

Built on raw Starlette — the shared foundation of FastAPI and FastHTML — so
one sub-app mounts identically into either host, and starcms never depends
on either framework.
"""

import typing

from starlette import applications, requests, responses, routing

if typing.TYPE_CHECKING:
    from starcms import core


def build_app(cms: "core.StarCMS") -> applications.Starlette:
    """Build the admin app for one StarCMS instance.

    The instance travels on app.state rather than in closures, so handlers
    and middleware can move to their own modules as the admin grows.
    """

    async def home(request: requests.Request) -> responses.HTMLResponse:
        models = request.app.state.cms.models
        items = "".join(f"<li>{m.__name__}</li>" for m in models)
        return responses.HTMLResponse(
            "<h1>starcms admin</h1>"
            f"<p>Registered models:</p><ul>{items}</ul>"
        )

    app = applications.Starlette(routes=[routing.Route("/", home)])
    app.state.cms = cms
    return app
