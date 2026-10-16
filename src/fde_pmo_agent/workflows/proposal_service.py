"""Create structured ADO proposals without performing side effects."""

from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from ..domain.models import ChangeOperation, PatchOperation, UpdateProposal
from ..domain.policy import AdoWritePolicy
from .proposal_store import InMemoryProposalStore


class ProposalService:
    """Stage validated changes for later one-time approval."""

    def __init__(self, session_id: str, store: InMemoryProposalStore, policy: AdoWritePolicy) -> None:
        self._session_id = session_id
        self._store = store
        self._policy = policy

    def stage_create(
        self,
        work_item_type: str,
        fields: Mapping[str, Any],
        reason: str,
        *,
        evidence: Sequence[str] = (),
    ) -> UpdateProposal:
        proposal = UpdateProposal(
            proposal_id=self._new_id(),
            session_id=self._session_id,
            operation=ChangeOperation.CREATE,
            reason=reason,
            work_item_type=work_item_type,
            fields=dict(fields),
            evidence=tuple(evidence),
        )
        return self._validate_and_add(proposal)

    def stage_update(
        self,
        work_item_id: int,
        expected_revision: int,
        patch: Sequence[PatchOperation],
        reason: str,
        *,
        evidence: Sequence[str] = (),
    ) -> UpdateProposal:
        proposal = UpdateProposal(
            proposal_id=self._new_id(),
            session_id=self._session_id,
            operation=ChangeOperation.UPDATE,
            reason=reason,
            work_item_id=work_item_id,
            expected_revision=expected_revision,
            patch=tuple(patch),
            evidence=tuple(evidence),
        )
        return self._validate_and_add(proposal)

    def stage_comment(
        self,
        work_item_id: int,
        expected_revision: int,
        comment: str,
        reason: str,
        *,
        evidence: Sequence[str] = (),
    ) -> UpdateProposal:
        proposal = UpdateProposal(
            proposal_id=self._new_id(),
            session_id=self._session_id,
            operation=ChangeOperation.COMMENT,
            reason=reason,
            work_item_id=work_item_id,
            expected_revision=expected_revision,
            comment=comment,
            evidence=tuple(evidence),
        )
        return self._validate_and_add(proposal)

    def _validate_and_add(self, proposal: UpdateProposal) -> UpdateProposal:
        self._policy.validate(proposal)
        return self._store.add(proposal)

    @staticmethod
    def _new_id() -> str:
        return f"prop_{secrets.token_urlsafe(12)}"
