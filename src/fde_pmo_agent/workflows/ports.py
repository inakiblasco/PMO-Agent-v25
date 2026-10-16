"""Provider-neutral interfaces implemented by mock and MCP adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from ..domain.models import PatchOperation, WorkItem


class AdoClient(Protocol):
    """ADO operations required by PMO skills and the write gateway."""

    async def get_work_item(self, work_item_id: int) -> WorkItem: ...

    async def list_overdue_work_items(self) -> Sequence[WorkItem]: ...

    async def create_work_item(
        self,
        work_item_type: str,
        fields: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> WorkItem: ...

    async def update_work_item(
        self,
        work_item_id: int,
        patch: Sequence[PatchOperation],
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WorkItem: ...

    async def add_work_item_comment(
        self,
        work_item_id: int,
        comment: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WorkItem: ...


class WorkIqClient(Protocol):
    """Read-only evidence search used by observe-task-board."""

    async def search_task_context(self, work_item_id: int, query: str) -> Sequence[Mapping[str, Any]]: ...


class MessageClient(Protocol):
    """Outbound messaging used by ask-task."""

    async def send_task_status_request(
        self,
        *,
        work_item_id: int,
        recipient: str,
        message: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...
