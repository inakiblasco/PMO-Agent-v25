"""In-memory ADO stand-in used before the MCP adapter is connected."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from ...domain.errors import RevisionConflictError
from ...domain.models import PatchOperation, WorkItem


class MockAdoClient:
    """Deterministic ADO implementation with revision and idempotency checks."""

    def __init__(self, work_items: Sequence[WorkItem] = ()) -> None:
        self._items = {item.id: copy.deepcopy(item) for item in work_items}
        self._next_id = max(self._items, default=1000) + 1
        self._results_by_key: dict[str, WorkItem] = {}

    async def get_work_item(self, work_item_id: int) -> WorkItem:
        return copy.deepcopy(self._items[work_item_id])

    async def list_overdue_work_items(self) -> Sequence[WorkItem]:
        now = datetime.now(timezone.utc)
        overdue: list[WorkItem] = []
        for item in self._items.values():
            due_value = item.fields.get("Microsoft.VSTS.Scheduling.DueDate")
            state = str(item.fields.get("System.State", "")).casefold()
            if not due_value or state in {"done", "closed", "resolved", "removed"}:
                continue
            due_at = datetime.fromisoformat(str(due_value).replace("Z", "+00:00"))
            if due_at < now:
                overdue.append(copy.deepcopy(item))
        return overdue

    async def create_work_item(
        self,
        work_item_type: str,
        fields: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> WorkItem:
        if existing := self._results_by_key.get(idempotency_key):
            return copy.deepcopy(existing)
        item = WorkItem(id=self._next_id, revision=1, work_item_type=work_item_type, fields=dict(fields))
        self._next_id += 1
        self._items[item.id] = item
        self._results_by_key[idempotency_key] = copy.deepcopy(item)
        return copy.deepcopy(item)

    async def update_work_item(
        self,
        work_item_id: int,
        patch: Sequence[PatchOperation],
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WorkItem:
        if existing := self._results_by_key.get(idempotency_key):
            return copy.deepcopy(existing)
        item = self._require_revision(work_item_id, expected_revision)
        for operation in patch:
            item.fields[operation.path.removeprefix("/fields/")] = operation.value
        item.revision += 1
        self._results_by_key[idempotency_key] = copy.deepcopy(item)
        return copy.deepcopy(item)

    async def add_work_item_comment(
        self,
        work_item_id: int,
        comment: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> WorkItem:
        if existing := self._results_by_key.get(idempotency_key):
            return copy.deepcopy(existing)
        item = self._require_revision(work_item_id, expected_revision)
        item.comments.append(comment)
        item.revision += 1
        self._results_by_key[idempotency_key] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def _require_revision(self, work_item_id: int, expected_revision: int) -> WorkItem:
        item = self._items[work_item_id]
        if item.revision != expected_revision:
            raise RevisionConflictError(
                f"Work Item #{work_item_id} is revision {item.revision}, expected {expected_revision}."
            )
        return item
