"""Tests for MCP Tasks (protocol 2025-11-25).

Covers the in-process task store, the extension's ``tasks/*`` handlers, and the
end-to-end flow over an in-memory client negotiated at 2025-11-25.

Note: the bundled SDK client sieves ``tools/call`` responses against
``CallToolResult`` and so cannot parse a task-augmented ``CreateTaskResult``.
``_allow_task_results`` relaxes exactly that client-side check for the tests that
exercise the augmented-call path; the server is unaffected.
"""

from __future__ import annotations

import asyncio
import time

import mcp_types as t
import mcp_types.methods as methods
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from mcp_tool_suite.context import build_context
from mcp_tool_suite.server import build_mcp_server
from mcp_tool_suite.services.tasks import TaskStore
from mcp_tool_suite.tasks_extension import TASKS_PROTOCOL_VERSIONS, TasksExtension


def _allow_task_results(monkeypatch: pytest.MonkeyPatch) -> None:
    original = methods.validate_server_result

    def loose(method, version, data, **kwargs):  # type: ignore[no-untyped-def]
        if method == "tools/call" and isinstance(data, dict) and "task" in data:
            return None
        return original(method, version, data, **kwargs)

    monkeypatch.setattr(methods, "validate_server_result", loose)


def _task_call(tool: str, arguments: dict, ttl: int = 60_000) -> t.CallToolRequest:
    return t.CallToolRequest(
        params=t.CallToolRequestParams(
            name=tool, arguments=arguments, task=t.TaskMetadata(ttl=ttl)
        )
    )


async def _wait_for_status(client: Client, task_id: str, target: set[str]) -> t.GetTaskResult:
    for _ in range(400):
        got = await client.session.send_request(
            t.GetTaskRequest(params=t.GetTaskRequestParams(task_id=task_id)), t.GetTaskResult
        )
        if got.status in target:
            return got
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {task_id} never reached {target}")


# --- TaskStore ---------------------------------------------------------------


def test_store_create_get_complete():
    store = TaskStore()
    record = store.create(ttl_ms=1000, poll_interval_ms=50)
    assert record.status == "working"
    assert record.poll_interval_ms == 50
    assert store.get(record.task_id) is record

    store.complete(record.task_id, {"ok": True})
    completed = store.get(record.task_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.result == {"ok": True}


def test_store_unknown_ids_return_none():
    store = TaskStore()
    assert store.get("missing") is None
    assert store.cancel("missing") is None
    assert store.complete("missing", 1) is None
    assert store.fail("missing", "boom") is None


def test_store_cancel_is_terminal():
    store = TaskStore()
    record = store.create()
    cancelled = store.cancel(record.task_id)
    assert cancelled is not None and cancelled.status == "cancelled"
    # A late completion must not resurrect a cancelled task.
    store.complete(record.task_id, "late")
    assert store.get(record.task_id).status == "cancelled"


def test_store_ttl_expiry():
    store = TaskStore(default_ttl_ms=1)
    record = store.create(ttl_ms=1)
    time.sleep(0.02)
    assert store.get(record.task_id) is None
    assert store.list() == []


def test_store_list_is_created_order():
    store = TaskStore()
    first = store.create()
    time.sleep(0.005)
    second = store.create()
    assert [r.task_id for r in store.list()] == [first.task_id, second.task_id]


def test_store_maps_to_wire_task_with_integer_ttl():
    record = TaskStore().create(ttl_ms=1234)
    wire = record.to_wire()
    assert wire.task_id == record.task_id
    assert wire.status == "working"
    assert wire.ttl == 1234  # never None: the wire Task requires a ttl


# --- extension handlers ------------------------------------------------------


def test_extension_result_requires_completion():
    ext = TasksExtension(["web_research"])
    record = ext.store.create()
    with pytest.raises(MCPError):
        asyncio.run(
            ext._handle_result(None, t.GetTaskPayloadRequestParams(task_id=record.task_id))
        )


def test_extension_handlers_reject_unknown_task():
    ext = TasksExtension(["web_research"])
    with pytest.raises(MCPError):
        asyncio.run(ext._handle_get(None, t.GetTaskRequestParams(task_id="nope")))
    with pytest.raises(MCPError):
        asyncio.run(ext._handle_result(None, t.GetTaskPayloadRequestParams(task_id="nope")))
    with pytest.raises(MCPError):
        asyncio.run(ext._handle_cancel(None, t.CancelTaskRequestParams(task_id="nope")))


# --- server wiring -----------------------------------------------------------


def test_capabilities_advertise_tasks(settings):
    server = build_mcp_server(build_context(settings))
    capabilities = server._lowlevel_server.get_capabilities()
    assert capabilities.tasks is not None
    assert capabilities.tasks.list is not None
    assert capabilities.tasks.cancel is not None
    assert capabilities.tasks.requests.tools.call is not None


def test_tools_list_reports_task_support(settings):
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server, mode="legacy") as client:
            tools = await client.list_tools()
            execution = {tool.name: tool.execution for tool in tools.tools}
            assert execution["web_research"].task_support == "optional"
            assert execution["generate_report"].task_support == "optional"
            assert execution["usage_stats"] is None

    asyncio.run(scenario())


def test_tasks_methods_version_gated_off_modern_wire(settings):
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server) as client:  # negotiates the modern 2026-07-28 wire
            with pytest.raises(MCPError):
                await client.session.send_request(
                    t.GetTaskRequest(params=t.GetTaskRequestParams(task_id="x")),
                    t.GetTaskResult,
                )

    asyncio.run(scenario())


# --- end-to-end --------------------------------------------------------------


def test_task_lifecycle_end_to_end(settings, monkeypatch):
    _allow_task_results(monkeypatch)
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server, mode="legacy") as client:
            created = await client.session.send_request(
                _task_call("web_research", {"query": "what is mcp"}), t.CreateTaskResult
            )
            task_id = created.task.task_id
            assert created.task.status == "working"

            final = await _wait_for_status(client, task_id, {"completed", "failed"})
            assert final.status == "completed"

            listed = await client.session.send_request(t.ListTasksRequest(), t.ListTasksResult)
            assert any(task.task_id == task_id for task in listed.tasks)

            result = await client.session.send_request(
                t.GetTaskPayloadRequest(params=t.GetTaskPayloadRequestParams(task_id=task_id)),
                t.CallToolResult,
            )
            assert result.is_error is False
            assert result.content

    asyncio.run(scenario())


def test_augmented_result_matches_direct_call(settings, monkeypatch):
    _allow_task_results(monkeypatch)
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server, mode="legacy") as client:
            direct = await client.call_tool("web_research", {"query": "grounding"})

            created = await client.session.send_request(
                _task_call("web_research", {"query": "grounding"}), t.CreateTaskResult
            )
            await _wait_for_status(client, created.task.task_id, {"completed"})
            deferred = await client.session.send_request(
                t.GetTaskPayloadRequest(
                    params=t.GetTaskPayloadRequestParams(task_id=created.task.task_id)
                ),
                t.CallToolResult,
            )

            direct_text = direct.content[0].text
            assert deferred.content[0].text == direct_text

    asyncio.run(scenario())


def test_non_task_tool_is_rejected(settings, monkeypatch):
    _allow_task_results(monkeypatch)
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server, mode="legacy") as client:
            with pytest.raises(MCPError) as excinfo:
                await client.session.send_request(
                    _task_call("usage_stats", {}), t.CreateTaskResult
                )
            assert excinfo.value.code == t.INVALID_PARAMS

    asyncio.run(scenario())


def test_cancel_reports_status(settings, monkeypatch):
    _allow_task_results(monkeypatch)
    server = build_mcp_server(build_context(settings))

    async def scenario() -> None:
        async with Client(server, mode="legacy") as client:
            created = await client.session.send_request(
                _task_call("web_research", {"query": "x"}), t.CreateTaskResult
            )
            await _wait_for_status(client, created.task.task_id, {"completed", "failed"})
            cancelled = await client.session.send_request(
                t.CancelTaskRequest(
                    params=t.CancelTaskRequestParams(task_id=created.task.task_id)
                ),
                t.CancelTaskResult,
            )
            # Cancelling an already-finished task is a no-op: status is unchanged.
            assert cancelled.status in {"completed", "failed", "cancelled"}

    asyncio.run(scenario())


def test_task_augmentation_requires_2025_11_25():
    assert TASKS_PROTOCOL_VERSIONS == frozenset({"2025-11-25"})
