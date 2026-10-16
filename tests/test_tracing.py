"""Tests for local JSONL execution tracing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_framework import (
    AgentContext,
    AgentResponse,
    AgentResponseUpdate,
    Content,
    AgentSession,
    FunctionInvocationContext,
    Message,
    ResponseStream,
    tool,
)

from fde_pmo_agent.agent.tracing import (
    TRACE_RUN_ID_KWARG,
    AgentExecutionTraceMiddleware,
    ExecutionTraceRecorder,
    FunctionExecutionTraceMiddleware,
)


class ExecutionTraceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.recorder = ExecutionTraceRecorder(Path(self.temp_dir.name), max_chars=2_000)

    def _events(self, run_id: str) -> list[dict[str, object]]:
        path = self.recorder.trace_path(run_id)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    async def test_agent_query_and_result_share_one_run_id(self) -> None:
        middleware = AgentExecutionTraceMiddleware(self.recorder)
        context = AgentContext(
            agent=object(),
            messages=[Message("user", ["期限切れのタスクを確認して"])],
            session=AgentSession(session_id="session-1"),
        )

        async def call_next() -> None:
            context.result = AgentResponse(messages=Message("assistant", ["確認しました"]))

        await middleware.process(context, call_next)

        run_id = context.function_invocation_kwargs[TRACE_RUN_ID_KWARG]
        events = self._events(run_id)
        self.assertEqual([event["event"] for event in events], ["query", "agent_result"])
        self.assertEqual({event["session_id"] for event in events}, {"session-1"})
        self.assertIn("期限切れ", json.dumps(events[0], ensure_ascii=False))
        self.assertIn("確認しました", json.dumps(events[1], ensure_ascii=False))

    async def test_skill_and_tool_calls_record_arguments_and_results(self) -> None:
        middleware = FunctionExecutionTraceMiddleware(self.recorder)
        run_id = self.recorder.new_run_id()
        session = AgentSession(session_id="session-2")

        @tool(name="load_skill")
        def load_skill(skill_name: str) -> str:
            return skill_name

        skill_context = FunctionInvocationContext(
            function=load_skill,
            arguments={"skill_name": "observe-task-board"},
            session=session,
            kwargs={TRACE_RUN_ID_KWARG: run_id},
        )

        async def load_next() -> None:
            skill_context.result = "# Observe task board"

        await middleware.process(skill_context, load_next)

        @tool(name="ado_get_work_item")
        def get_work_item(work_item_id: int) -> dict[str, int]:
            return {"id": work_item_id}

        tool_context = FunctionInvocationContext(
            function=get_work_item,
            arguments={"work_item_id": 101},
            session=session,
            kwargs={TRACE_RUN_ID_KWARG: run_id},
        )

        async def tool_next() -> None:
            tool_context.result = {"id": 101}

        await middleware.process(tool_context, tool_next)

        events = self._events(run_id)
        self.assertEqual(
            [event["event"] for event in events],
            ["skill_call", "skill_result", "tool_call", "tool_result"],
        )
        self.assertIn("observe-task-board", json.dumps(events[0]))
    async def test_stream_failure_is_recorded_as_agent_error(self) -> None:
        middleware = AgentExecutionTraceMiddleware(self.recorder)
        context = AgentContext(
            agent=object(),
            messages=[Message("user", ["test"])],
            session=AgentSession(session_id="session-error"),
            stream=True,
        )

        async def failing_updates():
            raise RuntimeError("403 forbidden")
            yield

        async def call_next() -> None:
            context.result = ResponseStream(failing_updates(), finalizer=AgentResponse.from_updates)

        await middleware.process(context, call_next)
        with self.assertRaisesRegex(RuntimeError, "403"):
            async for _ in context.result:
                pass

        run_id = context.function_invocation_kwargs[TRACE_RUN_ID_KWARG]
        events = self._events(run_id)
        self.assertEqual([event["event"] for event in events], ["query", "agent_error"])

    async def test_stream_success_is_recorded_as_agent_result(self) -> None:
        middleware = AgentExecutionTraceMiddleware(self.recorder)
        context = AgentContext(
            agent=object(),
            messages=[Message("user", ["test"])],
            session=AgentSession(session_id="session-success"),
            stream=True,
        )

        async def successful_updates():
            yield AgentResponseUpdate(
                role="assistant",
                contents=[Content.from_text("stream complete")],
                finish_reason="stop",
            )

        async def call_next() -> None:
            context.result = ResponseStream(successful_updates(), finalizer=AgentResponse.from_updates)

        await middleware.process(context, call_next)
        async for _ in context.result:
            pass

        run_id = context.function_invocation_kwargs[TRACE_RUN_ID_KWARG]
        events = self._events(run_id)
        self.assertEqual([event["event"] for event in events], ["query", "agent_result"])
        self.assertIn("stream complete", json.dumps(events[-1]))

    def test_sensitive_fields_are_redacted_and_large_payloads_are_bounded(self) -> None:
        run_id = self.recorder.new_run_id()
        self.recorder.record(
            run_id,
            "tool_result",
            session_id=None,
            data={"api_key": "do-not-log", "result": "x" * 10_000},
        )

        event = self._events(run_id)[0]
        serialized = json.dumps(event)
        self.assertNotIn("do-not-log", serialized)
        self.assertLess(len(serialized), 2_500)


if __name__ == "__main__":
    unittest.main()
