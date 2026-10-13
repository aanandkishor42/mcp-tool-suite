"""Pluggable tool registry.

Every tool is a small plugin implementing ``ToolPlugin``: a name, a description
(for the LLM to choose from) and a ``create`` factory that closes over the
``AppContext`` to return an async callable with a typed signature. The registry
applies them all to an ``MCPServer`` — add or remove a plugin and the server's
tool list changes with no other code touched.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Awaitable, Callable, Protocol, Sequence

from mcp_tool_suite.context import AppContext

ToolCallable = Callable[..., Awaitable[Any]]


class ToolPlugin(Protocol):
    name: str
    description: str

    def create(self, ctx: AppContext) -> ToolCallable: ...

    # A plugin may optionally define ``meta: dict[str, Any]`` to stamp ``_meta`` on
    # the tool (e.g. MCP Apps ``{"ui": {"resourceUri": ...}}``); the registry reads
    # it with ``getattr(plugin, "meta", None)``.
    #
    # A plugin may also optionally define ``task_support: "optional" | "required"``
    # to advertise that it can run as a background MCP Task (2025-11-25); see
    # ``mcp_tool_suite.tools.task_augmentable_tools``.


def _tracked(name: str, fn: ToolCallable, ctx: AppContext) -> ToolCallable:
    """Wrap a tool callable so every invocation is recorded on ``ctx.usage``.

    ``functools.wraps`` keeps ``__wrapped__``/``__signature__`` intact, so the
    schema the server derives from ``inspect.signature(..., eval_str=True)`` is
    unchanged while the wrapper still observes latency and success/failure.
    """

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        ok = True
        try:
            return await fn(*args, **kwargs)
        except Exception:
            ok = False
            raise
        finally:
            ctx.usage.record_tool(
                name, duration_ms=(time.perf_counter() - start) * 1000, ok=ok
            )

    return wrapped


class ToolRegistry:
    def __init__(self, plugins: Sequence[ToolPlugin]) -> None:
        self._plugins = list(plugins)

    def names(self) -> list[str]:
        return [plugin.name for plugin in self._plugins]

    def apply(self, server: Any, ctx: AppContext) -> list[str]:
        """Register every plugin's callable on an MCPServer. Returns tool names."""
        registered: list[str] = []
        for plugin in self._plugins:
            callable_ = plugin.create(ctx)
            server.add_tool(
                _tracked(plugin.name, callable_, ctx),
                name=plugin.name,
                description=plugin.description,
                meta=getattr(plugin, "meta", None),
            )
            registered.append(plugin.name)
        return registered
