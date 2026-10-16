"""Tests for Foundry hosting and hosted-session runtime isolation."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from agent_framework import AgentSession, FunctionInvocationContext

from fde_pmo_agent.agent.tools import build_agent_tools
from fde_pmo_agent.hosting.foundry import create_azure_credential, create_foundry_agent, create_foundry_host
from fde_pmo_agent.runtime import MockPmoRuntime, SessionRuntimeRegistry
from fde_pmo_agent.settings import PmoSettings


def foundry_settings() -> PmoSettings:
    return PmoSettings.from_mapping(
        {
            "PMO_RUNTIME": "foundry",
            "FOUNDRY_PROJECT_ENDPOINT": "https://project.services.ai.azure.com",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
        }
    )


class FoundryHostingTests(unittest.TestCase):

    def test_cli_credential_mode_uses_azure_cli_user(self) -> None:
        settings = PmoSettings.from_mapping({"AZURE_CREDENTIAL_MODE": "cli"})

        with patch("fde_pmo_agent.hosting.foundry.AzureCliCredential") as credential_type:
            credential = create_azure_credential(settings)

        credential_type.assert_called_once_with()
        self.assertIs(credential, credential_type.return_value)

    def test_managed_identity_credential_mode_is_explicit(self) -> None:
        settings = PmoSettings.from_mapping({"AZURE_CREDENTIAL_MODE": "managed_identity"})

        with patch("fde_pmo_agent.hosting.foundry.ManagedIdentityCredential") as credential_type:
            credential = create_azure_credential(settings)

        credential_type.assert_called_once_with()
        self.assertIs(credential, credential_type.return_value)

    def test_azd_credential_mode_uses_developer_cli_user(self) -> None:
        settings = PmoSettings.from_mapping({"AZURE_CREDENTIAL_MODE": "azd"})
        with patch("fde_pmo_agent.hosting.foundry.AzureDeveloperCliCredential") as credential_type:
            credential = create_azure_credential(settings)
        credential_type.assert_called_once_with()
        self.assertIs(credential, credential_type.return_value)

    def test_foundry_agent_uses_configured_client_and_disables_model_history_storage(self) -> None:
        captured: dict[str, Any] = {}
        credential = object()

        def client_factory(**kwargs: Any) -> object:
            captured.update(kwargs)
            return object()

        agent = create_foundry_agent(
            foundry_settings(),
            credential=credential,
            client_factory=client_factory,
        )

        self.assertEqual(captured["project_endpoint"], "https://project.services.ai.azure.com")
        self.assertEqual(captured["model"], "gpt-4.1-mini")
        self.assertIs(captured["credential"], credential)
        self.assertFalse(agent.default_options["store"])
        self.assertEqual(len(agent.default_options["tools"]), 8)
        middleware_names = {type(item).__name__ for item in agent.middleware}
        self.assertTrue(
            {"AgentExecutionTraceMiddleware", "FunctionExecutionTraceMiddleware"} <= middleware_names
        )

    def test_foundry_host_wraps_the_harness_agent(self) -> None:
        captured: list[Any] = []
        expected_server = object()

        def server_factory(agent: Any, **kwargs: Any) -> object:
            captured.append(agent)
            self.assertEqual(kwargs, {"history_source": "agent"})
            return expected_server

        server = create_foundry_host(
            foundry_settings(),
            credential=object(),
            client_factory=lambda **_: object(),
            server_factory=server_factory,
        )

        self.assertIs(server, expected_server)
        self.assertEqual(captured[0].name, "FdePmoAgent")

    def test_foundry_host_rejects_mock_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "PMO_RUNTIME"):
            create_foundry_agent(PmoSettings.from_mapping({}), credential=object())


class SessionRuntimeRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = SessionRuntimeRegistry()
        bootstrap = MockPmoRuntime.create("bootstrap")
        self.tools = {
            item.name: item
            for item in build_agent_tools(bootstrap, runtime_resolver=self.registry.resolve)
        }

    async def _propose(self, session_id: str) -> dict[str, Any]:
        tool = self.tools["propose_work_item_update"]
        arguments = {
            "work_item_id": 101,
            "expected_revision": 4,
            "patch_json": '[{"op":"replace","path":"/fields/System.State","value":"Resolved"}]',
            "reason": "Confirmed complete.",
            "evidence_json": '["teams-thread-42"]',
        }
        context = FunctionInvocationContext(
            function=tool,
            arguments=arguments,
            session=AgentSession(session_id=session_id),
        )
        return await tool.invoke(arguments=arguments, context=context, skip_parsing=True)

    async def test_proposals_are_isolated_by_hosted_agent_session(self) -> None:
        first = await self._propose("session-a")
        second = await self._propose("session-b")

        first_runtime = self.registry.get("session-a")
        second_runtime = self.registry.get("session-b")
        self.assertIsNotNone(first_runtime)
        self.assertIsNotNone(second_runtime)
        self.assertIsNot(first_runtime, second_runtime)
        self.assertEqual(first_runtime.proposal_store.get(first["proposal_id"]).session_id, "session-a")
        self.assertEqual(second_runtime.proposal_store.get(second["proposal_id"]).session_id, "session-b")

    async def test_hosted_tool_without_session_fails_closed(self) -> None:
        tool = self.tools["ado_list_overdue_work_items"]
        with self.assertRaisesRegex(RuntimeError, "session ID"):
            await tool.invoke(arguments={}, skip_parsing=True)
