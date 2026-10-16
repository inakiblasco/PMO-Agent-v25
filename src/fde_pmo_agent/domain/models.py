"""Structured records exchanged across the PMO domain boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ChangeOperation(StrEnum):
    """ADO write operations supported by the gateway."""

    CREATE = "create"
    UPDATE = "update"
    COMMENT = "comment"


class ProposalStatus(StrEnum):
    """Lifecycle states for a change proposal."""

    PENDING = "pending"
    APPLYING = "applying"
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PatchOperation:
    """One JSON Patch-like ADO field change."""

    op: str
    path: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "path": self.path, "value": self.value}


@dataclass(slots=True)
class WorkItem:
    """Provider-neutral representation of an ADO Work Item."""

    id: int
    revision: int
    work_item_type: str
    fields: dict[str, Any]
    comments: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "revision": self.revision,
            "work_item_type": self.work_item_type,
            "fields": dict(self.fields),
            "comments": list(self.comments),
        }


@dataclass(slots=True)
class UpdateProposal:
    """Exact ADO change waiting for one-time approval."""

    proposal_id: str
    session_id: str
    operation: ChangeOperation
    reason: str
    work_item_id: int | None = None
    expected_revision: int | None = None
    work_item_type: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    patch: tuple[PatchOperation, ...] = ()
    comment: str | None = None
    evidence: tuple[str, ...] = ()
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    applied_at: datetime | None = None
    result: dict[str, Any] | None = None

    @property
    def summary(self) -> str:
        """Return the canonical change shown in the approval request."""
        if self.operation is ChangeOperation.CREATE:
            fields = ", ".join(f"{name}={value!r}" for name, value in sorted(self.fields.items()))
            return f"Create {self.work_item_type}: {fields}"
        if self.operation is ChangeOperation.COMMENT:
            return (
                f"Add comment to Work Item #{self.work_item_id} "
                f"at revision {self.expected_revision}: {self.comment!r}"
            )
        changes = ", ".join(
            f"{item.op} {item.path.removeprefix('/fields/')}={item.value!r}" for item in self.patch
        )
        return f"Update Work Item #{self.work_item_id} at revision {self.expected_revision}: {changes}"

    @property
    def digest(self) -> str:
        """Bind an approval to the exact stored proposal content."""
        payload = {
            "proposal_id": self.proposal_id,
            "session_id": self.session_id,
            "operation": self.operation.value,
            "reason": self.reason,
            "work_item_id": self.work_item_id,
            "expected_revision": self.expected_revision,
            "work_item_type": self.work_item_type,
            "fields": self.fields,
            "patch": [item.to_dict() for item in self.patch],
            "comment": self.comment,
            "evidence": self.evidence,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_public_dict(self) -> dict[str, Any]:
        """Return the proposal data presented to the model and approval host."""
        return {
            "proposal_id": self.proposal_id,
            "operation": self.operation.value,
            "summary": self.summary,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "digest": self.digest,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Minimal audit event that excludes raw WorkIQ content."""

    event_type: str
    session_id: str
    subject_id: str
    detail: dict[str, Any]
    occurred_at: datetime = field(default_factory=utc_now)
