"""Mock WorkIQ search and outbound messaging services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from ...workflows.ports import AdoClient
from ...workflows.proposal_store import InMemoryAuditStore
from ...domain.errors import MessagePolicyError
from ...domain.models import AuditEvent


class MockWorkIqClient:
    """Return bounded evidence records without retaining raw M365 bodies."""

    def __init__(self, evidence: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> None:
        self._evidence = {key: [dict(item) for item in value] for key, value in (evidence or {}).items()}

    async def search_task_context(self, work_item_id: int, query: str) -> Sequence[Mapping[str, Any]]:
        del query
        return [dict(item) for item in self._evidence.get(work_item_id, ())]


class MockMessageClient:
    """Record automatic messages while enforcing assignee and frequency rules."""

    def __init__(
        self,
        *,
        session_id: str,
        ado: AdoClient,
        audit: InMemoryAuditStore,
        minimum_interval: timedelta = timedelta(hours=24),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_id = session_id
        self._ado = ado
        self._audit = audit
        self._minimum_interval = minimum_interval
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sent_by_key: dict[str, dict[str, Any]] = {}
        self._last_sent_by_item: dict[int, datetime] = {}

    async def send_task_status_request(
        self,
        *,
        work_item_id: int,
        recipient: str,
        message: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        if existing := self._sent_by_key.get(idempotency_key):
            return dict(existing)

        item = await self._ado.get_work_item(work_item_id)
        assignee = str(item.fields.get("System.AssignedTo", ""))
        if recipient.casefold() != assignee.casefold():
            raise MessagePolicyError("A status request may only be sent to the current ADO assignee.")
        if not message.strip():
            raise MessagePolicyError("A status request must not be empty.")

        now = self._now()
        if last_sent := self._last_sent_by_item.get(work_item_id):
            if now - last_sent < self._minimum_interval:
                raise MessagePolicyError("A status request was already sent within the configured interval.")

        result = {
            "message_id": f"mock-message-{len(self._sent_by_key) + 1}",
            "work_item_id": work_item_id,
            "recipient": recipient,
            "status": "sent",
        }
        self._sent_by_key[idempotency_key] = result
        self._last_sent_by_item[work_item_id] = now
        self._audit.append(
            AuditEvent(
                event_type="task_status_request_sent",
                session_id=self._session_id,
                subject_id=str(work_item_id),
                detail={"message_id": result["message_id"], "recipient": recipient},
            )
        )
        return dict(result)

    @property
    def sent_messages(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._sent_by_key.values())
