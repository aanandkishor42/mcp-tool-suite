"""Tests for the MCP Apps usage-dashboard widget (io.modelcontextprotocol/ui)."""

from __future__ import annotations

import asyncio

from mcp import Client
from mcp.client import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

from mcp_tool_suite.context import build_context
from mcp_tool_suite.server import build_mcp_server
from mcp_tool_suite.tools.dashboard import DASHBOARD_HTML, DASHBOARD_URI

_APPS_SUPPORT = advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})


def test_extension_is_advertised(settings):
    server = build_mcp_server(build_context(settings))
    capabilities = server._lowlevel_server.get_capabilities()
    assert capabilities.extensions is not None
    assert EXTENSION_ID in capabilities.extensions


def test_dashboard_resource_listed_and_readable(settings):
    server = build_mcp_server(build_context(settings))

    resources = asyncio.run(server.list_resources())
    match = [r for r in resources if str(r.uri) == DASHBOARD_URI]
    assert match, f"{DASHBOARD_URI} not in resources/list"
    assert match[0].mime_type == APP_MIME_TYPE

    contents = asyncio.run(server.read_resource(DASHBOARD_URI))
    assert contents[0].mime_type == APP_MIME_TYPE
    assert contents[0].content == DASHBOARD_HTML


def test_usage_stats_tool_carries_ui_meta(settings):
    server = build_mcp_server(build_context(settings))
    tools = asyncio.run(server.list_tools())
    usage = next(t for t in tools if t.name == "usage_stats")
    assert usage.meta is not None
    assert usage.meta["ui"]["resourceUri"] == DASHBOARD_URI


def test_apps_client_negotiates_and_reads_widget(settings):
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server, extensions=[_APPS_SUPPORT]) as client:
            ext = client.server_capabilities.extensions or {}
            assert EXTENSION_ID in ext

            tools = await client.list_tools()
            usage = next(t for t in tools.tools if t.name == "usage_stats")
            assert usage.meta["ui"]["resourceUri"] == DASHBOARD_URI

            resource = (await client.list_resources()).resources[0]
            assert str(resource.uri) == DASHBOARD_URI

            read = await client.read_resource(DASHBOARD_URI)
            assert read.contents[0].text == DASHBOARD_HTML

    asyncio.run(scenario())


def test_usage_stats_returns_text_fallback(settings):
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server) as client:  # no Apps advertised: text-only client
            result = await client.call_tool("usage_stats", {})
            texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
            assert any("Usage" in text for text in texts)

    asyncio.run(scenario())
