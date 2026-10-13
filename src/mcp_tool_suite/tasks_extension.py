"""MCP Tasks extension (protocol 2025-11-25).

Provides server-side task-augmented execution for long-running tools:

* ``tasks/get`` — poll a task's state.
* ``tasks/list`` — enumerate live tasks.
* ``tasks/cancel`` — request cancellation.
* ``tasks/result`` — fetch the original ``tools/call`` result once complete.

A ``tools/call`` carrying a ``task`` object is short-circuited: the tool runs in
the background and a ``CreateTaskResult`` is returned immediately.

Why this is not a plain :class:`~mcp.server.extension.Extension`:

* The SDK sieves ``tools/call`` results against ``CallToolResult``, so the
  ``CreateTaskResult`` a task-augmented call must return can only be emitted by
  short-circuiting **above** the handler sieve — i.e. from a server middleware,
  which extensions cannot contribute. :meth:`TasksExtension.install` appends it.
* The SDK never advertises ``ServerCapabilities.tasks`` (2025-11-25 only) and
  never exposes ``Tool.execution.taskSupport``; :meth:`TasksExtension.install`
  fills both gaps.

Everything is version-gated to 2025-11-25, the only revision that defines tasks
(the revision 2026-07-28 dropped them from core).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp_types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    CancelTaskRequestParams,
    CancelTaskResult,
    CreateTaskResult,
    GetTaskPayloadRequestParams,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksResult,
    PaginatedRequestParams,
    ServerTasksCapability,
    ServerTasksRequestsCapability,
    TasksCallCapability,
    TasksCancelCapability,
    TasksListCapability,
    TasksToolsCapability,
)

from mcp_tool_suite.services.tasks import DEFAULT_TTL_MS, TaskRecord, TaskStore

logger = logging.getLogger(__name__)

#: Tasks were introduced in 2025-11-25 and removed from the core in 2026-07-28.
TASKS_PROTOCOL_VERSIONS = frozenset({"2025-11-25"})


class TasksExtension(Extension):
    """Serves ``tasks/*`` and augments declared tools with background execution."""

    identifier = "io.modelcontextprotocol/tasks"

    def __init__(
        self,
        task_tools: Sequence[str] = (),
        *,
        default_ttl_ms: int = DEFAULT_TTL_MS,
        poll_interval_ms: int | None = None,
    ) -> None:
        self._task_tools = frozenset(task_tools)
        self._poll_interval_ms = poll_interval_ms
        self.store = TaskStore(default_ttl_ms=default_ttl_ms)
        self._server: Any = None
        # Live background runs, keyed by task id, so `tasks/cancel` can stop them.
        self._runners: dict[str, asyncio.Task[None]] = {}

    # -- extension surface ------------------------------------------------

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding(
                method="tasks/get",
                params_type=GetTaskRequestParams,
                handler=self._handle_get,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
            MethodBinding(
                method="tasks/list",
                params_type=PaginatedRequestParams,
                handler=self._handle_list,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
            MethodBinding(
                method="tasks/cancel",
                params_type=CancelTaskRequestParams,
                handler=self._handle_cancel,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
            MethodBinding(
                method="tasks/result",
                params_type=GetTaskPayloadRequestParams,
                handler=self._handle_result,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
        )

    def install(self, server: Any) -> None:
        """Attach the task-augmentation middleware and advertise ``tasks``.

        Must be called once after the ``MCPServer`` has had its tools registered.
        """
        self._server = server
        server.middleware.append(self._intercept_tool_call)
        self._advertise_tasks_capability(server)

    # -- tasks/* handlers -------------------------------------------------

    async def _handle_get(self, ctx: Any, params: GetTaskRequestParams) -> GetTaskResult:
        record = self.store.get(params.task_id)
        if record is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Unknown task: {params.task_id}")
        return GetTaskResult(**record.to_wire().model_dump())

    async def _handle_list(self, ctx: Any, params: PaginatedRequestParams) -> ListTasksResult:
        return ListTasksResult(tasks=[record.to_wire() for record in self.store.list()])

    async def _handle_cancel(self, ctx: Any, params: CancelTaskRequestParams) -> CancelTaskResult:
        if self.store.get(params.task_id) is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Unknown task: {params.task_id}")
        record = self.store.cancel(params.task_id)
        # Stop the background run too, not just the status flag. The runner's
        # CancelledError handler also cancels the record (idempotent).
        runner = self._runners.get(params.task_id)
        if runner is not None and not runner.done():
            runner.cancel()
        assert record is not None
        return CancelTaskResult(**record.to_wire().model_dump())

    async def _handle_result(self, ctx: Any, params: GetTaskPayloadRequestParams) -> Any:
        record = self.store.get(params.task_id)
        if record is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Unknown task: {params.task_id}")
        if record.status != "completed" or record.result is None:
            raise MCPError(
                code=INVALID_PARAMS,
                message=f"Task {params.task_id} has no result (status: {record.status})",
            )
        return record.result

    # -- tools/call augmentation -----------------------------------------

    async def _intercept_tool_call(self, ctx: Any, call_next: Callable[[Any], Any]) -> Any:
        """Short-circuit a task-augmented ``tools/call`` into a background run."""
        if ctx.method != "tools/call" or ctx.protocol_version not in TASKS_PROTOCOL_VERSIONS:
            return await call_next(ctx)
        raw = ctx.params
        if not isinstance(raw, Mapping) or raw.get("task") is None:
            return await call_next(ctx)

        params = CallToolRequestParams.model_validate(raw, by_name=False)
        if params.name not in self._task_tools:
            raise MCPError(
                code=INVALID_PARAMS,
                message=f"Tool {params.name!r} does not support task-augmented execution",
            )

        ttl_ms = params.task.ttl if params.task is not None else None
        record = self.store.create(ttl_ms=ttl_ms, poll_interval_ms=self._poll_interval_ms)
        self._spawn(record.task_id, ctx, params)
        return CreateTaskResult(task=record.to_wire())

    def _spawn(self, task_id: str, ctx: Any, params: CallToolRequestParams) -> None:
        """Run the tool in the background, independent of the request's scope."""
        loop = asyncio.get_running_loop()
        runner = loop.create_task(self._run(task_id, ctx, params))
        self._runners[task_id] = runner
        runner.add_done_callback(lambda finished: self._on_runner_done(task_id, finished))

    async def _run(self, task_id: str, ctx: Any, params: CallToolRequestParams) -> None:
        try:
            result: CallToolResult = await self._server._handle_call_tool(ctx, params)
        except asyncio.CancelledError:
            self.store.cancel(task_id)
            raise
        except Exception as exc:  # a tool/runner failure becomes a failed task
            logger.exception("background task %s failed", task_id)
            self.store.fail(task_id, f"{type(exc).__name__}: {exc}")
        else:
            self.store.complete(task_id, result)

    def _on_runner_done(self, task_id: str, runner: "asyncio.Task[None]") -> None:
        self._runners.pop(task_id, None)
        # Retrieve the exception so asyncio does not warn about it going unread.
        if not runner.cancelled() and runner.exception() is not None:
            logger.debug("background task %s ended with %r", task_id, runner.exception())

    # -- capability advertisement ----------------------------------------

    def _advertise_tasks_capability(self, server: Any) -> None:
        """Add ``ServerCapabilities.tasks`` to the initialize/discover result.

        The SDK builds capabilities from registered handlers only and has no slot
        for tasks, so we wrap ``get_capabilities`` on the low-level server.
        """
        low = server._lowlevel_server
        original = low.get_capabilities

        def with_tasks(*args: Any, **kwargs: Any) -> Any:
            capabilities = original(*args, **kwargs)
            capabilities.tasks = ServerTasksCapability(
                list=TasksListCapability(),
                cancel=TasksCancelCapability(),
                requests=ServerTasksRequestsCapability(
                    tools=TasksToolsCapability(call=TasksCallCapability())
                ),
            )
            return capabilities

        low.get_capabilities = with_tasks


def build_tasks_extension(
    task_tools: Sequence[str],
    *,
    default_ttl_ms: int = DEFAULT_TTL_MS,
    poll_interval_ms: int | None = None,
) -> TasksExtension:
    return TasksExtension(task_tools, default_ttl_ms=default_ttl_ms, poll_interval_ms=poll_interval_ms)


__all__ = ["TASKS_PROTOCOL_VERSIONS", "TaskRecord", "TasksExtension", "build_tasks_extension"]
