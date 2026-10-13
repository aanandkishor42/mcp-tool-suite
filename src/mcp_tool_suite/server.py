"""Server assembly: build the MCP server, expose it over HTTP or stdio."""

from __future__ import annotations

from typing import Any

import uvicorn
from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from mcp_types import ListToolsResult, ToolExecution
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_tool_suite.auth import BearerAuthMiddleware, OAuth2Server
from mcp_tool_suite.auth.middleware import OAuth2ResourceServerMiddleware
from mcp_tool_suite.config import Settings, get_settings
from mcp_tool_suite.context import AppContext, build_context
from mcp_tool_suite.registry import ToolRegistry
from mcp_tool_suite.tasks_extension import TasksExtension, build_tasks_extension
from mcp_tool_suite.tools import default_plugins, task_augmentable_tools
from mcp_tool_suite.tools.dashboard import DASHBOARD_HTML, DASHBOARD_URI

INSTRUCTIONS = (
    "This server exposes a suite of document and knowledge tools. Typical flow: "
    "index_document to load a PDF/URL/text into a collection, then document_qa to "
    "ask grounded questions with citations, or semantic_search for raw passages. "
    "analyze_document summarizes any document without indexing it."
)


def build_registry() -> ToolRegistry:
    return ToolRegistry(default_plugins())


class ToolSuiteServer(MCPServer):
    """``MCPServer`` that additionally advertises ``Tool.execution.taskSupport``.

    The SDK has no plumbing for the 2025-11-25 ``execution`` field, so we stamp
    it onto the ``tools/list`` result for the tools that can run as tasks.
    """

    def __init__(self, *args: Any, task_tool_names: Any = (), **kwargs: Any) -> None:
        self._task_tool_names = frozenset(task_tool_names)
        super().__init__(*args, **kwargs)

    async def _handle_list_tools(self, ctx: Any, params: Any) -> ListToolsResult:
        result = await super()._handle_list_tools(ctx, params)
        for tool in result.tools:
            if tool.name in self._task_tool_names:
                tool.execution = ToolExecution(task_support="optional")
        return result


def build_apps() -> Apps:
    """The MCP Apps extension: serves the interactive usage dashboard widget."""
    apps = Apps()
    apps.add_html_resource(
        DASHBOARD_URI,
        DASHBOARD_HTML,
        title="Usage dashboard",
        description="Interactive view of tool/LLM call counts, latency and estimated cost.",
    )
    return apps


def build_tasks(ctx: AppContext) -> TasksExtension | None:
    """The MCP Tasks extension, unless disabled in settings."""
    if not ctx.settings.tasks_enabled:
        return None
    return build_tasks_extension(
        task_augmentable_tools(),
        default_ttl_ms=ctx.settings.tasks_default_ttl_ms,
        poll_interval_ms=ctx.settings.tasks_poll_interval_ms,
    )


def build_mcp_server(ctx: AppContext) -> MCPServer:
    extensions: list[Any] = [build_apps()]
    tasks = build_tasks(ctx)
    if tasks is not None:
        extensions.append(tasks)

    server = ToolSuiteServer(
        name=ctx.settings.server_name,
        version=ctx.settings.server_version,
        instructions=INSTRUCTIONS,
        extensions=extensions,
        task_tool_names=task_augmentable_tools(),
    )
    build_registry().apply(server, ctx)
    if tasks is not None:
        tasks.install(server)
    return server


def _issuer_for(settings: Settings) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"http://{settings.host}:{settings.port}"


def build_http_app(settings: Settings | None = None) -> Any:
    """Return a Starlette app exposing the MCP endpoint plus a public /health."""
    settings = settings or get_settings()
    ctx = build_context(settings)
    server = build_mcp_server(ctx)

    tool_names = build_registry().names()

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "server": settings.server_name,
                "version": settings.server_version,
                "transport": settings.transport,
                "llm_provider": settings.llm_provider,
                "embed_provider": settings.embed_provider,
                "vector_store": settings.vector_store,
                "auth_mode": settings.auth_mode,
                "tools": tool_names,
            }
        )

    @server.custom_route("/stats", methods=["GET"])
    async def stats(_: Request) -> JSONResponse:
        return JSONResponse(ctx.usage.summary())

    # Custom routes must be registered before the app is materialised.
    app = server.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        stateless_http=settings.stateless_http,
        host=settings.host,
    )

    if settings.auth_mode == "oauth2":
        issuer = _issuer_for(settings)
        oauth = OAuth2Server.bootstrap(
            data_dir=settings.data_dir,
            issuer=issuer,
            resource_url=f"{issuer}{settings.mcp_path}",
            token_ttl=settings.oauth_token_ttl,
            refresh_ttl=settings.oauth_refresh_ttl,
            demo_user=settings.oauth_demo_user,
            demo_password=settings.oauth_demo_password,
        )
        app.state.oauth = oauth  # keep the store/keys alive for the app lifetime
        # The MCP app router contains only the /mcp route (no catch-all), so the
        # authorization-server endpoints can be appended safely.
        app.router.routes.extend(oauth.routes)
        app.add_middleware(
            OAuth2ResourceServerMiddleware,
            public_key=oauth.public_key,
            issuer=oauth.issuer,
            resource_url=oauth.resource_url,
            guard_path=settings.mcp_path,
        )
    elif settings.auth_mode == "bearer":
        app.add_middleware(
            BearerAuthMiddleware,
            api_key=settings.api_key,
            protected_path=settings.mcp_path,
        )

    return app


def run_stdio(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    server = build_mcp_server(build_context(settings))
    server.run("stdio")


def main() -> None:
    settings = get_settings()
    if settings.transport == "stdio":
        run_stdio(settings)
        return
    uvicorn.run(build_http_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
