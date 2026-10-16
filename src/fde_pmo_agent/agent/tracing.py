"""JSONL execution tracing for PMO Agent runs, skills, and tools."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from agent_framework import (
    AgentContext,
    AgentMiddleware,
    AgentResponse,
    FunctionInvocationContext,
    FunctionMiddleware,
    ResponseStream,
)

logger = logging.getLogger(__name__)

TRACE_RUN_ID_KWARG = "pmo_trace_run_id"
_SKILL_TOOL_NAMES = {"load_skill", "read_skill_resource", "run_skill_script"}
_SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "connection_string",
    "password",
    "secret",
    "token",
}


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _session_id(session: Any) -> str | None:
    value = getattr(session, "session_id", None)
    return str(value) if value else None


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _jsonable(value: Any, *, max_chars: int, depth: int = 0) -> Any:
    if depth >= 10:
        return "<maximum-depth-reached>"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"...<truncated {len(value) - max_chars} chars>"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>"
            if _is_sensitive_key(key)
            else _jsonable(item, max_chars=max_chars, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item, max_chars=max_chars, depth=depth + 1) for item in value]

    for method_name in ("to_dict", "model_dump"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _jsonable(method(), max_chars=max_chars, depth=depth + 1)
            except Exception:
                logger.debug("Could not serialize %s with %s.", type(value).__name__, method_name, exc_info=True)
    return repr(value)


class ExecutionTraceRecorder:
    """Write one bounded JSON Lines trace file per Agent execution."""

    def __init__(self, directory: str | Path = "log", *, max_chars: int = 20_000) -> None:
        if max_chars < 256:
            raise ValueError("Trace max_chars must be at least 256.")
        self.directory = Path(directory)
        self.max_chars = max_chars
        self._write_lock = Lock()

    def new_run_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{timestamp}-{uuid4().hex[:12]}"

    def trace_path(self, run_id: str) -> Path:
        return self.directory / f"pmo-agent-{run_id}.jsonl"

    def record(
        self,
        run_id: str,
        event: str,
        *,
        session_id: str | None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        safe_data = _jsonable(dict(data or {}), max_chars=self.max_chars)
        encoded_data = json.dumps(safe_data, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(encoded_data) > self.max_chars:
            safe_data = {
                "truncated": True,
                "preview": encoded_data[: self.max_chars],
                "original_chars": len(encoded_data),
            }
        entry = {
            "timestamp": _utc_timestamp(),
            "run_id": run_id,
            "session_id": session_id,
            "event": event,
            "data": safe_data,
        }
        try:
            with self._write_lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                with self.trace_path(run_id).open("a", encoding="utf-8") as trace_file:
                    trace_file.write(json.dumps(entry, ensure_ascii=False, default=str))
                    trace_file.write("\n")
        except OSError:
            # Observability must not break an Agent execution.
            logger.exception("Could not write PMO Agent execution trace.")


class AgentExecutionTraceMiddleware(AgentMiddleware):
    """Trace the submitted query and final Agent result."""

    def __init__(self, recorder: ExecutionTraceRecorder) -> None:
        self.recorder = recorder

    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        run_id = self.recorder.new_run_id()
        session_id = _session_id(context.session)
        context.function_invocation_kwargs[TRACE_RUN_ID_KWARG] = run_id
        self.recorder.record(
            run_id,
            "query",
            session_id=session_id,
            data={"messages": context.messages},
        )

        stream_updates: list[Any] = []
        stream_failed = False
        result_recorded = False

        def record_collected_result() -> None:
            nonlocal result_recorded
            if stream_failed or result_recorded:
                return
            self.recorder.record(
                run_id,
                "agent_result",
                session_id=session_id,
                data={"response": AgentResponse.from_updates(stream_updates)},
            )
            result_recorded = True

        try:
            await call_next()
        except Exception as exc:
            self.recorder.record(
                run_id,
                "agent_error",
                session_id=session_id,
                data={"error": exc},
            )
            raise

        if context.stream and isinstance(context.result, ResponseStream):
            original_stream = context.result

            async def traced_updates():
                nonlocal stream_failed
                try:
                    async for update in original_stream:
                        stream_updates.append(update)
                        yield update
                    record_collected_result()
                except Exception as exc:
                    stream_failed = True
                    self.recorder.record(
                        run_id,
                        "agent_error",
                        session_id=session_id,
                        data={"error": exc},
                    )
                    raise

            context.result = ResponseStream(traced_updates(), finalizer=AgentResponse.from_updates)
        elif not context.stream:
            self.recorder.record(
                run_id,
                "agent_result",
                session_id=session_id,
                data={"response": context.result},
            )


class FunctionExecutionTraceMiddleware(FunctionMiddleware):
    """Trace Skills and model-invoked tools with arguments and results."""

    def __init__(self, recorder: ExecutionTraceRecorder) -> None:
        self.recorder = recorder

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        run_id = str(context.kwargs.get(TRACE_RUN_ID_KWARG) or self.recorder.new_run_id())
        session_id = _session_id(context.session)
        function_name = context.function.name
        prefix = "skill" if function_name in _SKILL_TOOL_NAMES else "tool"
        common = {
            "name": function_name,
            "arguments": context.arguments,
            "call_id": context.metadata.get("call_id"),
        }
        self.recorder.record(run_id, f"{prefix}_call", session_id=session_id, data=common)
        try:
            await call_next()
        except Exception as exc:
            self.recorder.record(
                run_id,
                f"{prefix}_error",
                session_id=session_id,
                data={**common, "error": exc},
            )
            raise
        self.recorder.record(
            run_id,
            f"{prefix}_result",
            session_id=session_id,
            data={**common, "result": context.result},
        )


def build_trace_middleware(recorder: ExecutionTraceRecorder) -> list[Any]:
    """Build the Agent Framework middleware pair sharing one recorder."""
    return [
        AgentExecutionTraceMiddleware(recorder),
        FunctionExecutionTraceMiddleware(recorder),
    ]
