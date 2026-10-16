"""Approval-bound ADO write gateway."""

from __future__ import annotations

import asyncio

from ..domain.errors import ProposalIntegrityError, RevisionConflictError, WriteOutcomeUnknownError
from ..domain.models import AuditEvent, ChangeOperation, UpdateProposal, WorkItem
from ..domain.policy import AdoWritePolicy
from .ports import AdoClient
from .proposal_store import InMemoryAuditStore, InMemoryProposalStore


class AdoWriteGateway:
    """Validate and execute a stored proposal through a private ADO client.

    The ADO client held by this class is intentionally not model-facing. The
    Agent Framework adapter added in a later layer exposes only ``apply`` as an
    approval-required tool.
    """

    def __init__(
        self,
        *,
        session_id: str,
        client: AdoClient,
        proposals: InMemoryProposalStore,
        audit: InMemoryAuditStore,
        policy: AdoWritePolicy,
    ) -> None:
        self._session_id = session_id
        self._client = client
        self._proposals = proposals
        self._audit = audit
        self._policy = policy
        self._apply_lock = asyncio.Lock()

    async def apply(self, proposal_id: str, digest: str, change_summary: str) -> dict[str, object]:
        """Apply one exact pending proposal after the tool host grants approval."""
        async with self._apply_lock:
            proposal = self._proposals.get_pending(proposal_id, session_id=self._session_id)
            self._verify_approval_binding(proposal, digest, change_summary)
            self._policy.validate(proposal)
            proposal = self._proposals.claim_pending(proposal_id, session_id=self._session_id)
            self._audit.append(
                AuditEvent(
                    event_type="ado_change_execution_started",
                    session_id=self._session_id,
                    subject_id=proposal.proposal_id,
                    detail={"operation": proposal.operation.value, "summary": proposal.summary},
                )
            )
            try:
                result = await self._execute(proposal)
            except (RevisionConflictError, WriteOutcomeUnknownError) as exc:
                self._record_failure(proposal, exc)
                self._proposals.mark_rejected(proposal.proposal_id, {"error_type": type(exc).__name__})
                raise
            except asyncio.CancelledError:
                self._audit.append(AuditEvent(
                    event_type="ado_change_execution_cancelled",
                    session_id=self._session_id, subject_id=proposal.proposal_id,
                    detail={"requires_reconciliation": True},
                ))
                self._proposals.mark_rejected(proposal.proposal_id, {"requires_reconciliation": True})
                raise
            except Exception as exc:
                self._record_failure(proposal, exc)
                self._proposals.release_pending(proposal.proposal_id)
                raise
            public_result = result.to_dict()
            self._proposals.mark_applied(proposal.proposal_id, public_result)
            self._audit.append(
                AuditEvent(
                    event_type="ado_change_applied",
                    session_id=self._session_id,
                    subject_id=proposal.proposal_id,
                    detail={"work_item_id": result.id, "revision": result.revision},
                )
            )
            return public_result

    async def _execute(self, proposal: UpdateProposal) -> WorkItem:
        if proposal.operation is ChangeOperation.CREATE:
            return await self._client.create_work_item(
                proposal.work_item_type or "",
                proposal.fields,
                idempotency_key=proposal.proposal_id,
            )

        work_item_id = proposal.work_item_id or 0
        current = await self._client.get_work_item(work_item_id)
        if current.revision != proposal.expected_revision:
            raise RevisionConflictError(
                f"Work Item #{current.id} is revision {current.revision}; "
                f"the proposal expected revision {proposal.expected_revision}."
            )
        if proposal.operation is ChangeOperation.UPDATE:
            return await self._client.update_work_item(
                current.id,
                proposal.patch,
                expected_revision=current.revision,
                idempotency_key=proposal.proposal_id,
            )
        return await self._client.add_work_item_comment(
            current.id,
            proposal.comment or "",
            expected_revision=current.revision,
            idempotency_key=proposal.proposal_id,
        )

    def _record_failure(self, proposal: UpdateProposal, error: Exception) -> None:
        self._audit.append(
            AuditEvent(
                event_type="ado_change_execution_failed",
                session_id=self._session_id,
                subject_id=proposal.proposal_id,
                detail={"error_type": type(error).__name__},
            )
        )

    @staticmethod
    def _verify_approval_binding(proposal: UpdateProposal, digest: str, change_summary: str) -> None:
        if digest != proposal.digest:
            raise ProposalIntegrityError("The approved digest does not match the stored proposal.")
        if change_summary != proposal.summary:
            raise ProposalIntegrityError("The approved summary does not match the stored proposal.")
