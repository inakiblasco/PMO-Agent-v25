"""Write boundary contracts and uncertain-outcome handling without network calls."""

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fde_pmo_agent.domain.errors import ProposalStateError, RevisionConflictError, WriteOutcomeUnknownError
from fde_pmo_agent.domain.models import PatchOperation, ProposalStatus
from fde_pmo_agent.integrations.mcp.ado import AdoMcpClient
from fde_pmo_agent.integrations.mcp.ado_write import AdoWriteMcpClient
from fde_pmo_agent.runtime import PmoRuntime
from fde_pmo_agent.hosting.foundry import create_foundry_agent
from fde_pmo_agent.settings import PmoSettings
from test_ado_toolbox import config, record, response


class AdoWriteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = AsyncMock()
        self.session.list_tools.return_value = SimpleNamespace(tools=[SimpleNamespace(
            name="ado___wit_work_item_write", inputSchema={"properties": {
                k: {} for k in ["action", "project", "id", "updates", "workItemType", "fields"]
            }},
        )])

        @asynccontextmanager
        async def sessions():
            yield self.session

        self.sessions = sessions
        self.writer = AdoWriteMcpClient(config(), sessions)
        self.reader = AdoMcpClient(config(), sessions)
        self.runtime = PmoRuntime.readonly("s", self.reader, writer=self.writer, due_date_field="Custom.Due")

    async def test_update_prepends_atomic_revision_test_and_preserves_patch(self):
        updated = record()
        updated["rev"] = 4
        updated["fields"]["System.State"] = "Done"
        self.session.call_tool.side_effect = [response(record()), response(record()), response(updated)]
        proposal = self.runtime.proposals.stage_update(
            7, 3, [PatchOperation("replace", "/fields/System.State", "Done")], "Confirmed completion",
        )
        result = await self.runtime.write_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)
        self.assertEqual(result["revision"], 4)
        self.session.call_tool.assert_awaited_with("ado___wit_work_item_write", arguments={
            "action": "update", "project": "Project", "id": 7, "updates": [
                {"op": "Test", "path": "/rev", "value": 3},
                {"op": "Replace", "path": "/fields/System.State", "value": "Done"},
            ],
        })
        with self.assertRaises(ProposalStateError):
            await self.runtime.write_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)

    async def test_create_and_comment_use_gateway_and_exact_contracts(self):
        create = self.runtime.proposals.stage_create("Task", {"System.Title": "New task", "Custom.Due": None}, "Agreed")
        self.session.call_tool.return_value = response(record(**{"System.Title": "New task"}))
        await self.runtime.write_gateway.apply(create.proposal_id, create.digest, create.summary)
        self.session.call_tool.assert_awaited_with("ado___wit_work_item_write", arguments={
            "action": "create", "project": "Project", "workItemType": "Task", "fields": [
                {"name": "System.Title", "value": "New task"}, {"name": "Custom.Due", "value": None},
            ],
        })
        item = record(); item["rev"] = 4
        self.session.call_tool.side_effect = [response(record()), response(record()), response(item)]
        comment = self.runtime.proposals.stage_comment(7, 3, "Confirmed.", "Record result")
        result = await self.runtime.write_gateway.apply(comment.proposal_id, comment.digest, comment.summary)
        self.assertEqual(result["comments"], ["Confirmed."])
        updates = self.session.call_tool.call_args.kwargs["arguments"]["updates"]
        self.assertEqual(updates, [{"op": "Test", "path": "/rev", "value": 3},
                                   {"op": "Add", "path": "/fields/System.History", "value": "Confirmed."}])

    async def test_conflict_prevents_dispatch(self):
        self.session.call_tool.return_value = response(record())
        with self.assertRaises(RevisionConflictError):
            await self.writer.update_work_item(7, [PatchOperation("replace", "/fields/System.State", "Done")],
                                               expected_revision=2, idempotency_key="p")
        self.session.list_tools.assert_not_awaited()
        self.assertEqual(self.session.call_tool.await_count, 1)

    async def test_unconfirmed_create_consumes_proposal_without_retry(self):
        self.session.call_tool.side_effect = TimeoutError("secret")
        proposal = self.runtime.proposals.stage_create("Task", {"System.Title": "New task"}, "Agreed")
        with self.assertRaises(WriteOutcomeUnknownError) as caught:
            await self.runtime.write_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(self.runtime.proposal_store.get(proposal.proposal_id).status, ProposalStatus.REJECTED)
        with self.assertRaises(ProposalStateError):
            await self.runtime.write_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)
        self.assertEqual(self.session.call_tool.await_count, 1)

    async def test_bad_response_after_dispatch_is_unconfirmed(self):
        for result in (response({}), {"isError": True}, response(record(**{"System.TeamProject": "Other"}))):
            self.session.call_tool.return_value = result
            with self.assertRaises(WriteOutcomeUnknownError):
                await self.writer.create_work_item("Task", {"System.Title": "Title"}, idempotency_key="p")

    async def test_cancelled_write_cannot_be_replayed(self):
        self.session.call_tool.side_effect = asyncio.CancelledError()
        proposal = self.runtime.proposals.stage_create("Task", {"System.Title": "New task"}, "Agreed")
        with self.assertRaises(asyncio.CancelledError):
            await self.runtime.write_gateway.apply(proposal.proposal_id, proposal.digest, proposal.summary)
        self.assertEqual(self.runtime.proposal_store.get(proposal.proposal_id).status, ProposalStatus.REJECTED)

    async def test_missing_write_tool_prevents_dispatch(self):
        self.session.list_tools.return_value = SimpleNamespace(tools=[])
        from fde_pmo_agent.domain.errors import WritePolicyError
        with self.assertRaises(WritePolicyError):
            await self.writer.create_work_item("Task", {"System.Title": "Title"}, idempotency_key="p")
        self.session.call_tool.assert_not_awaited()

    def test_create_approval_summary_includes_all_proposed_fields(self):
        proposal = self.runtime.proposals.stage_create(
            "Task", {"System.Title": "Title", "System.Description": "Description", "System.Tags": "tag"}, "Agreed",
        )
        self.assertIn("System.Description='Description'", proposal.summary)
        self.assertIn("System.Tags='tag'", proposal.summary)

    def test_hosting_keeps_read_and_write_clients_separate_and_requires_approval(self):
        settings = PmoSettings.from_mapping({
            "PMO_RUNTIME": "foundry", "FOUNDRY_PROJECT_ENDPOINT": "https://p.services.ai.azure.com",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "model", "ADO_MODE": "toolbox",
            "ADO_TOOLBOX_ENDPOINT": config().endpoint, "ADO_WRITE_TOOLBOX_ENDPOINT": config().endpoint,
            "ADO_PROJECT": "Project",
        })
        with patch("fde_pmo_agent.hosting.foundry.SessionRuntimeRegistry") as registry:
            agent = create_foundry_agent(settings, credential=object(), client_factory=lambda **_: object())
            runtime = registry.call_args.args[0]("s")
        self.assertIsInstance(runtime.ado, AdoMcpClient)
        self.assertNotIsInstance(runtime.ado, AdoWriteMcpClient)
        self.assertIsInstance(runtime.write_gateway._client, AdoWriteMcpClient)
        tools = {t.name: t for t in agent.default_options["tools"]}
        self.assertEqual(len(tools), 8)
        self.assertEqual(tools["apply_approved_ado_change"].approval_mode, "always_require")
