"""Synthetic remote MCP contracts; no credentials or network calls."""

import json
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import httpx
from azure.core.credentials import AccessToken

from fde_pmo_agent.integrations.mcp.ado import (
    AdoMcpClient, AdoMcpError, AdoToolboxConfig, FoundryAdoSessionFactory,
)
from fde_pmo_agent.domain.errors import WritePolicyError, MessagePolicyError
from fde_pmo_agent.runtime import PmoRuntime
from fde_pmo_agent.settings import PmoSettings
from fde_pmo_agent.agent.tools import build_agent_tools
from fde_pmo_agent.hosting.foundry import create_foundry_agent
from agent_framework import AgentSession, FunctionInvocationContext


def config():
    return AdoToolboxConfig(
        "https://sample.services.ai.azure.com/api/projects/p/toolboxes/ado/mcp?api-version=v1",
        "Project", "query-id", "Custom.Due", ("Done",),
    )


def record(item_id=7, **extra):
    return {"id": item_id, "rev": 3, "fields": {
        "System.TeamProject": "Project", "System.WorkItemType": "Task", "System.State": "Active",
        "Custom.Due": "2000-01-01T00:00:00Z", **extra,
    }}


def response(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


class AdoToolboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = AsyncMock()
        self.opened = 0
        self.closed = 0

        @asynccontextmanager
        async def sessions():
            self.opened += 1
            try:
                yield self.session
            finally:
                self.closed += 1

        self.sessions = sessions
        self.client = AdoMcpClient(config(), sessions)

    async def test_get_normalizes_and_checks_project_and_id(self):
        self.session.call_tool.return_value = response(record(**{
            "System.AssignedTo": {"uniqueName": "user@example.invalid"},
        }))
        item = await self.client.get_work_item(7)
        self.assertEqual(item.fields["System.AssignedTo"], "user@example.invalid")
        self.session.call_tool.assert_awaited_with("ado___wit_work_item", arguments={
            "action": "get", "project": "Project", "id": 7,
        })
        self.assertEqual((self.opened, self.closed), (1, 1))
        for payload in (record(8), record(**{"System.TeamProject": "Other"}), {"id": True}):
            self.session.call_tool.return_value = response(payload)
            with self.assertRaises(AdoMcpError):
                await self.client.get_work_item(7)

    async def test_query_hydration_and_overdue_filter(self):
        self.session.call_tool.side_effect = [
            response({"workItems": [{"id": i} for i in (7, 8, 9)]}),
            {"structuredContent": [record(), record(8, **{"System.State": "Done"}),
                                   record(9, **{"Custom.Due": "2999-01-01T00:00:00Z"})]},
        ]
        self.assertEqual([i.id for i in await self.client.list_overdue_work_items()], [7])
        first = self.session.call_tool.call_args_list[0]
        self.assertEqual(first.args, ("ado___wit_query",))
        self.assertEqual(first.kwargs["arguments"], {
            "action": "get_results", "project": "Project", "id": "query-id", "top": 200,
        })
        self.assertEqual(self.session.call_tool.await_count, 2)
        self.assertEqual(self.opened, 1)

    async def test_empty_query_skips_batch_and_incomplete_query_fails(self):
        self.session.call_tool.return_value = response({"workItems": []})
        self.assertEqual(await self.client.list_overdue_work_items(), [])
        self.session.call_tool.assert_awaited_once()
        for payload in ({"workItems": [], "continuationToken": "next"},
                        {"workItems": [{"id": i} for i in range(1, 201)]},
                        {"workItems": [{"id": 7}, {"id": 7}]},
                        {"workItemRelations": []}):
            self.session.call_tool.return_value = response(payload)
            with self.assertRaises(AdoMcpError):
                await self.client.list_overdue_work_items()

    async def test_without_saved_query_uses_project_scoped_wiql(self):
        client = AdoMcpClient(replace(config(), query_id=""), self.sessions)
        self.session.call_tool.side_effect = [
            response({"workItems": [{"id": 7}]}), response([record()]),
        ]
        self.assertEqual([x.id for x in await client.list_overdue_work_items()], [7])
        self.assertEqual(self.session.call_tool.call_args_list[0].kwargs["arguments"], {
            "action": "wiql", "project": "Project", "top": 200,
            "wiql": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project",
        })

    async def test_undated_items_are_not_reported_as_overdue(self):
        self.session.call_tool.side_effect = [
            response({"workItems": [{"id": 7}]}), response([record(**{"Custom.Due": None})]),
        ]
        self.assertEqual(await self.client.list_overdue_work_items(), [])

    async def test_single_item_read_does_not_require_board_configuration(self):
        client = AdoMcpClient(AdoToolboxConfig(config().endpoint, "Project",
                                             server_label="AzureDevOpsMCPServer"), self.sessions)
        self.session.call_tool.return_value = response(record())
        self.assertEqual((await client.get_work_item(7)).id, 7)
        self.session.call_tool.assert_awaited_with("AzureDevOpsMCPServer___wit_work_item", arguments={
            "action": "get", "project": "Project", "id": 7,
        })
        with self.assertRaises(ValueError):
            await client.list_overdue_work_items()
        self.assertEqual(self.session.call_tool.await_count, 1)

    async def test_bad_batch_and_dates_fail(self):
        for batch in ([], [record(8)], [record(), record()],
                      [record(**{"Custom.Due": "2000-01-01"})]):
            self.session.call_tool.side_effect = [response({"workItems": [{"id": 7}]}), response(batch)]
            with self.assertRaises(AdoMcpError):
                await self.client.list_overdue_work_items()

    async def test_errors_are_sanitized_and_sessions_closed(self):
        for value in (None, {"isError": True, "content": [{"text": "secret"}]},
                      {"content": [{"type": "text", "text": "bad JSON"}]}):
            self.session.call_tool.return_value = value
            with self.assertRaises(AdoMcpError) as caught:
                await self.client.get_work_item(7)
            self.assertNotIn("secret", str(caught.exception))
        self.session.call_tool.side_effect = RuntimeError("secret")
        with self.assertRaises(AdoMcpError) as caught:
            await self.client.get_work_item(7)
        self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(self.opened, self.closed)

    async def test_readonly_runtime_blocks_writes_messages_and_mock_evidence(self):
        runtime = PmoRuntime.readonly("s", self.client)
        tools = build_agent_tools(runtime)
        self.assertEqual(len(tools), 8)
        self.assertFalse(any(t.name.startswith("ado.wit") for t in tools))
        with self.assertRaises(WritePolicyError):
            await self.client.create_work_item("Task", {}, idempotency_key="k")
        with self.assertRaises(MessagePolicyError):
            await runtime.messages.send_task_status_request()
        with self.assertRaises(MessagePolicyError):
            await runtime.workiq.search_task_context(7, "query")
        self.session.call_tool.assert_not_called()

    async def test_hosted_settings_select_real_adapter_and_existing_pmo_tools(self):
        settings = PmoSettings.from_mapping({
            "PMO_RUNTIME": "foundry", "FOUNDRY_PROJECT_ENDPOINT": "https://sample.services.ai.azure.com",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "model", "ADO_MODE": "toolbox_readonly",
            "ADO_TOOLBOX_ENDPOINT": config().endpoint, "ADO_PROJECT": "Project", "ADO_QUERY_ID": "query-id",
            "ADO_DUE_DATE_FIELD": "Custom.Due", "ADO_COMPLETED_STATES": "Done",
        })
        self.session.call_tool.return_value = response(record())
        with patch("fde_pmo_agent.integrations.mcp.ado.FoundryAdoSessionFactory", return_value=self.sessions):
            agent = create_foundry_agent(settings, credential=object(), client_factory=lambda **_: object())
        tools = {t.name: t for t in agent.default_options["tools"]}
        self.assertEqual(len(tools), 8)
        tool = tools["ado_get_work_item"]
        args = {"work_item_id": 7}
        for sid in ("a", "b"):
            context = FunctionInvocationContext(function=tool, arguments=args, session=AgentSession(session_id=sid))
            result = await tool.invoke(arguments=args, context=context, skip_parsing=True)
            self.assertEqual(result["id"], 7)
        self.assertEqual((self.opened, self.closed), (2, 2))
        self.assertFalse(any(type(m).__name__.endswith("ExecutionTraceMiddleware") for m in agent.middleware))

    async def test_sdk_transport_keeps_auth_and_request_context_without_publishing_tools(self):
        calls = []

        def handler(request):
            calls.append(dict(request.headers))
            return httpx.Response(200)

        credential = type("Credential", (), {"get_token": lambda self, scope: AccessToken("synthetic", 9999999999)})()
        factory = FoundryAdoSessionFactory(config(), credential)

        @asynccontextmanager
        async def transport(toolbox):
            self.assertFalse(toolbox.load_tools_flag)
            async with httpx.AsyncClient(auth=toolbox._httpx_client.auth,
                                         transport=httpx.MockTransport(handler)) as http:
                await http.get(config().endpoint)
            yield ("read", "write", lambda: None)

        @asynccontextmanager
        async def session(reader, writer):
            yield self.session

        from agent_framework_foundry_hosting import FoundryToolbox
        with patch.object(FoundryToolbox, "get_mcp_client", transport), patch("mcp.ClientSession", session):
            for call_id in ("first", "second"):
                context = type("Context", (), {"platform_headers": lambda self: {
                    "x-agent-foundry-call-id": call_id,
                }})()
                with patch("agent_framework_foundry_hosting._toolbox.get_request_context", return_value=context):
                    async with factory() as active:
                        self.assertIs(active, self.session)
        self.assertEqual([h["x-agent-foundry-call-id"] for h in calls], ["first", "second"])
        self.assertTrue(all(h["authorization"] == "Bearer synthetic" for h in calls))

    def test_endpoint_validation_prevents_forwarding_credentials_to_arbitrary_hosts(self):
        for endpoint in ("http://example.invalid/mcp", "https://example.invalid/mcp",
                         "https://x.services.ai.azure.com/anything",
                         "https://user:pass@x.services.ai.azure.com/api/projects/p/toolboxes/t/mcp"):
            with self.assertRaises(ValueError):
                replace(config(), endpoint=endpoint)
        with self.assertRaises(ValueError):
            PmoSettings.from_mapping({"ADO_MODE": "toolbox_readonly"})


if __name__ == "__main__":
    unittest.main()
