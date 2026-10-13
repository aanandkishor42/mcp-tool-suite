"""Pluggable tool registry.

Every tool is a small plugin implementing ``ToolPlugin``: a name, a description
(for the LLM to choose from) and a ``create`` factory that closes over the
``AppContext`` to return an async callable with a typed signature. The registry
applies them all to an ``MCPServer`` — add or remove a plugin and the server's
tool list changes with no other code touched.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, Sequence

from mcp_tool_suite.context import AppContext

ToolCallable = Callable[..., Awaitable[Any]]


class ToolPlugin(Protocol):
    name: str
    description: str

    def create(self, ctx: AppContext) -> ToolCallable: ...


class ToolRegistry:
    def __init__(self, plugins: Sequence[ToolPlugin]) -> None:
        self._plugins = list(plugins)

    def names(self) -> list[str]:
        return [plugin.name for plugin in self._plugins]

    def apply(self, server: Any, ctx: AppContext) -> list[str]:
        """Register every plugin's callable on an MCPServer. Returns tool names."""
        registered: list[str] = []
        for plugin in self._plugins:
            server.add_tool(
                plugin.create(ctx), name=plugin.name, description=plugin.description
            )
            registered.append(plugin.name)
        return registered
