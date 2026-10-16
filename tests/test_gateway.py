"""Tests for the provider-independent ADO write boundary."""

from __future__ import annotations

import asyncio
import unittest

from fde_pmo_agent.domain.errors import (
    ProposalIntegrityError,
    ProposalStateError,
    RevisionConflictError,
    WritePolicyError,
)
from fde_pmo_agent.workflows.ado_write_gateway import AdoWriteGateway
from fde_pmo_agent.workflows.proposal_service import ProposalService
from fde_pmo_agent.workflows.proposal_store import InMemoryAuditStore, InMemoryProposalStore
from fde_pmo_agent.domain.models import PatchOperation, ProposalStatus, WorkItem
from fde_pmo_agent.domain.policy import AdoWritePolicy
from fde_pmo_agent.integrations.mock.ado import MockAdoClient


class AdoWriteGatewayTests(unittest.IsolatedAsyncioTestCase):
    """Exercise every state-changing operation and its safety checks."""

    def setUp(self) -> None:
        self.session_id = "session-1"
        self.client = MockAdoClient(
            [
                WorkItem(
                    id=101,
                    revision=4,
                    work_item_type="Task",
                    fields={
                        "System.Title": "Prepare demo",
                        "System.State": "Active",
                        "System.AssignedTo": "alex@example.com",
                    },
                )
            ]
        )
        self.store = InMemoryProposalStore()
        self.audit = InMemoryAuditStore()
        self.policy = AdoWritePolicy()
        self.proposals = ProposalService(self.session_id, self.store, self.policy)
        self.gateway = AdoWriteGateway(
            session_id=self.session_id,
            client=self.client,
            proposals=self.store,
            audit=self.audit,
            policy=self.policy,
        )

    async def test_update_applies_exact_proposal_and_records_audit(self) -> None:
        proposal = self.proposals.stage_update(
            101,
            4,
            [PatchOperation("replace", "/fields/System.State", "Resolved")],
            "The assignee confirmed completion.",
            evidence=["teams-message-42"],
        )

        result = await self.gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)

        self.assertEqual(result["revision"], 5)
        self.assertEqual(result["fields"]["System.State"], "Resolved")
        self.assertIs(self.store.get(proposal.proposal_id).status, ProposalStatus.APPLIED)
        self.assertEqual(
            [event.event_type for event in self.audit.list_events()],
            ["ado_change_execution_started", "ado_change_applied"],
        )

    async def test_create_and_comment_are_supported(self) -> None:
        create = self.proposals.stage_create("Task", {"System.Title": "Follow up"}, "Create agreed action item.")
        created = await self.gateway.apply(create.proposal_id, create.digest, create.summary)
        comment = self.proposals.stage_comment(
            created["id"],
            created["revision"],
            "Status confirmed in Teams.",
            "Record the evidence summary.",
        )

        commented = await self.gateway.apply(comment.proposal_id, comment.digest, comment.summary)

        self.assertEqual(commented["comments"], ["Status confirmed in Teams."])
        self.assertEqual(commented["revision"], 2)

    async def test_revision_conflict_blocks_update_and_is_audited(self) -> None:
        proposal = self.proposals.stage_update(
            101,
            4,
            [PatchOperation("replace", "/fields/System.State", "Resolved")],
            "Proposed before a concurrent edit.",
        )
        await self.client.update_work_item(
            101,
            [PatchOperation("replace", "/fields/System.Title", "Changed elsewhere")],
            expected_revision=4,
            idempotency_key="external-change",
        )

        with self.assertRaises(RevisionConflictError):
            await self.gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)

        self.assertIs(self.store.get(proposal.proposal_id).status, ProposalStatus.REJECTED)
        self.assertEqual(self.audit.list_events()[-1].event_type, "ado_change_execution_failed")

    async def test_digest_or_summary_tampering_is_rejected(self) -> None:
        proposal = self.proposals.stage_comment(101, 4, "Progress noted.", "Record progress.")

        with self.assertRaises(ProposalIntegrityError):
            await self.gateway.apply(proposal.proposal_id, "wrong-digest", proposal.summary)
        with self.assertRaises(ProposalIntegrityError):
            await self.gateway.apply(proposal.proposal_id, proposal.digest, "Different change")

        self.assertEqual((await self.client.get_work_item(101)).comments, [])

    async def test_proposal_cannot_be_applied_twice(self) -> None:
        proposal = self.proposals.stage_comment(101, 4, "Progress noted.", "Record progress.")
        await self.gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)

        with self.assertRaises(ProposalStateError):
            await self.gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)

        self.assertEqual((await self.client.get_work_item(101)).comments, ["Progress noted."])

    async def test_proposal_is_bound_to_agent_session(self) -> None:
        proposal = self.proposals.stage_comment(101, 4, "Progress noted.", "Record progress.")
        other_gateway = AdoWriteGateway(
            session_id="session-2",
            client=self.client,
            proposals=self.store,
            audit=self.audit,
            policy=self.policy,
        )

        with self.assertRaises(ProposalStateError):
            await other_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)

    async def test_concurrent_gateways_execute_a_proposal_only_once(self) -> None:
        proposal = self.proposals.stage_comment(101, 4, "Progress noted.", "Record progress.")
        second_gateway = AdoWriteGateway(
            session_id=self.session_id,
            client=self.client,
            proposals=self.store,
            audit=self.audit,
            policy=self.policy,
        )

        results = await asyncio.gather(
            self.gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary),
            second_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary),
            return_exceptions=True,
        )

        successes = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, Exception)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], ProposalStateError)
        self.assertEqual((await self.client.get_work_item(101)).comments, ["Progress noted."])

    def test_disallowed_field_is_rejected_before_staging(self) -> None:
        with self.assertRaises(WritePolicyError):
            self.proposals.stage_update(
                101,
                4,
                [PatchOperation("replace", "/fields/System.Rev", 999)],
                "Attempt to overwrite a protected field.",
            )


if __name__ == "__main__":
    unittest.main()
