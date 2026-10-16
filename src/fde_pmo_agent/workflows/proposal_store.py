"""In-memory proposal and audit stores for the first implementation."""

from __future__ import annotations

from threading import RLock
from typing import Any

from ..domain.errors import ProposalNotFoundError, ProposalStateError
from ..domain.models import AuditEvent, ProposalStatus, UpdateProposal, utc_now


class InMemoryProposalStore:
    """Keep authorization state outside model-visible conversation memory."""

    def __init__(self) -> None:
        self._items: dict[str, UpdateProposal] = {}
        self._lock = RLock()

    def add(self, proposal: UpdateProposal) -> UpdateProposal:
        with self._lock:
            if proposal.proposal_id in self._items:
                raise ProposalStateError(f"Duplicate proposal ID: {proposal.proposal_id}")
            self._items[proposal.proposal_id] = proposal
            return proposal

    def get(self, proposal_id: str) -> UpdateProposal:
        with self._lock:
            try:
                return self._items[proposal_id]
            except KeyError as exc:
                raise ProposalNotFoundError(f"Proposal not found: {proposal_id}") from exc

    def get_pending(self, proposal_id: str, *, session_id: str) -> UpdateProposal:
        proposal = self.get(proposal_id)
        if proposal.session_id != session_id:
            raise ProposalStateError("The proposal belongs to a different Agent session.")
        if proposal.status is not ProposalStatus.PENDING:
            raise ProposalStateError(f"Proposal {proposal_id} is {proposal.status.value}, not pending.")
        return proposal

    def claim_pending(self, proposal_id: str, *, session_id: str) -> UpdateProposal:
        """Atomically reserve a proposal so concurrent gateways cannot execute it."""
        with self._lock:
            proposal = self.get_pending(proposal_id, session_id=session_id)
            proposal.status = ProposalStatus.APPLYING
            return proposal

    def release_pending(self, proposal_id: str) -> None:
        with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status is ProposalStatus.APPLYING:
                proposal.status = ProposalStatus.PENDING

    def mark_applied(self, proposal_id: str, result: dict[str, Any]) -> UpdateProposal:
        with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status is not ProposalStatus.APPLYING:
                raise ProposalStateError(f"Proposal {proposal_id} has already been processed.")
            proposal.status = ProposalStatus.APPLIED
            proposal.applied_at = utc_now()
            proposal.result = dict(result)
            return proposal

    def mark_rejected(self, proposal_id: str, result: dict[str, Any]) -> UpdateProposal:
        with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status is not ProposalStatus.APPLYING:
                raise ProposalStateError(f"Proposal {proposal_id} is not being applied.")
            proposal.status = ProposalStatus.REJECTED
            proposal.result = dict(result)
            return proposal


class InMemoryAuditStore:
    """Append-only audit store used by tests and the mock runtime."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = RLock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)
