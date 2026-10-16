"""Integration tests for local Skills and Agent Framework tool adapters."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from agent_framework import AgentSession, BaseChatClient, ChatResponse, Content, Message, SkillsSourceContext
from agent_framework._tools import FunctionInvocationLayer

from fde_pmo_agent.agent.factory import create_mock_pmo_agent
from fde_pmo_agent.agent.tools import build_agent_tools
from fde_pmo_agent.runtime import MockPmoRuntime, PmoRuntime
from fde_pmo_agent.domain.errors import MessagePolicyError
from fde_pmo_agent.domain.models import WorkItem
from fde_pmo_agent.integrations.mock.ado import MockAdoClient


class ScriptedChatClient(FunctionInvocationLayer, BaseChatClient):
    """Run the real SDK tool loop without a model or external services."""

    def __init__(self, respond):
        super().__init__()
        self.respond = respond

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        return ChatResponse(messages=[self.respond(messages, options)])


class AgentToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runtime = MockPmoRuntime.create("tool-test-session")
        self.tools = {item.name: item for item in build_agent_tools(self.runtime)}

    def test_only_ado_apply_tool_requires_approval(self) -> None:
        self.assertEqual(self.tools["apply_approved_ado_change"].approval_mode, "always_require")
        self.assertEqual(
            {tool.approval_mode for name, tool in self.tools.items() if name != "apply_approved_ado_change"},
            {"never_require"},
        )

    def test_injected_session_context_is_not_model_visible(self) -> None:
        for tool in self.tools.values():
            self.assertNotIn("context", tool.parameters().get("properties", {}))

    async def test_observe_tools_combine_overdue_ado_and_workiq_evidence(self) -> None:
        overdue = await self.tools["ado_list_overdue_work_items"].invoke(arguments={}, skip_parsing=True)
        evidence = await self.tools["workiq_search_task_context"].invoke(
            arguments={"work_item_id": 101, "query": "Prepare hackathon demo alex@example.com"},
            skip_parsing=True,
        )

        self.assertEqual([item["id"] for item in overdue], [101])
        self.assertEqual(evidence[0]["source_id"], "teams-thread-42")

    async def test_ask_task_sends_without_approval_but_enforces_recipient(self) -> None:
        send = self.tools["send_task_status_request"]
        arguments = {
            "work_item_id": 101,
            "recipient": "alex@example.com",
            "message": "Please share the current status for Work Item #101.",
        }
        first = await send.invoke(arguments=arguments, skip_parsing=True)
        repeated = await send.invoke(arguments=arguments, skip_parsing=True)

        self.assertEqual(first, repeated)
        self.assertEqual(len(self.runtime.messages.sent_messages), 1)
        with self.assertRaises(MessagePolicyError):
            await send.invoke(
                arguments={**arguments, "recipient": "someone-else@example.com"},
                skip_parsing=True,
            )

    async def test_proposal_tool_returns_values_bound_to_approval(self) -> None:
        proposal = await self.tools["propose_work_item_update"].invoke(
            arguments={
                "work_item_id": 101,
                "expected_revision": 4,
                "patch_json": '[{"op":"replace","path":"/fields/System.State","value":"Resolved"}]',
                "reason": "The assignee confirmed completion.",
                "evidence_json": '["teams-thread-42"]',
            },
            skip_parsing=True,
        )

        stored = self.runtime.proposal_store.get(proposal["proposal_id"])
        self.assertEqual(proposal["digest"], stored.digest)
        self.assertEqual(proposal["summary"], stored.summary)

    def test_harness_factory_registers_tools_and_skills_provider(self) -> None:
        agent = create_mock_pmo_agent(object(), self.runtime)
        tool_names = {item.name for item in agent.default_options["tools"]}
        provider_names = {type(item).__name__ for item in agent.context_providers}

        self.assertEqual(tool_names, set(self.tools))
        self.assertIn("SkillsProvider", provider_names)
        self.assertIn("TodoProvider", provider_names)
        self.assertNotIn("AgentModeProvider", provider_names)

    async def test_agent_framework_discovers_all_four_skills(self) -> None:
        agent = create_mock_pmo_agent(object(), self.runtime)
        provider = next(item for item in agent.context_providers if type(item).__name__ == "SkillsProvider")

        skills = await provider._source.get_skills(SkillsSourceContext(agent=agent))

        self.assertEqual(
            {skill.frontmatter.name for skill in skills},
            {
                "observe-task-board",
                "ask-task",
                "proposal-task-update",
                "update-task-board",
            },
        )


class ProposalWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.reader = AsyncMock(spec=MockAdoClient)
        self.writer = AsyncMock(spec=MockAdoClient)
        self.reader.get_work_item.return_value = WorkItem(6, 7, "Task", {"System.Title": "Validation task"})
        self.runtime = PmoRuntime.readonly("proposal-session", self.reader, writer=self.writer)
        self.session = AgentSession(session_id="proposal-session")

    async def test_proposal_only_reads_stages_and_shows_without_modes_or_writes(self) -> None:
        calls = []
        proposal = None

        def respond(messages, options):
            nonlocal proposal
            tool_names = {tool.name for tool in options["tools"]}
            self.assertTrue({"mode_get", "mode_set"}.isdisjoint(tool_names))
            self.assertNotIn("## Agent Mode", options.get("instructions", ""))
            if not calls:
                call = Content.from_function_call(
                    call_id="read", name="ado_get_work_item", arguments={"work_item_id": 6},
                )
            elif len(calls) == 1:
                result = next(c for m in messages for c in m.contents
                              if c.type == "function_result" and c.call_id == "read")
                item = json.loads(result.result)
                self.assertEqual((item["id"], item["revision"]), (6, 7))
                call = Content.from_function_call(
                    call_id="propose", name="propose_work_item_comment", arguments={
                        "work_item_id": item["id"], "expected_revision": item["revision"],
                        "comment": "Validation proposal only", "reason": "User requested a proposal only.",
                    },
                )
            else:
                result = next(c for m in messages for c in m.contents
                              if c.type == "function_result" and c.call_id == "propose")
                proposal = json.loads(result.result)
                return Message("assistant", [json.dumps(proposal)])
            calls.append(call.name)
            return Message("assistant", [call])

        agent = create_mock_pmo_agent(ScriptedChatClient(respond), self.runtime)
        response = await agent.run(
            "Read work item 6, then stage a comment proposal saying “Validation proposal only”. "
            "Show me the proposal, but do not apply it or modify Azure DevOps.",
            session=self.session,
        )
        self.assertEqual(calls, ["ado_get_work_item", "propose_work_item_comment"])
        returned_calls = [c.name for m in response.messages for c in m.contents if c.type == "function_call"]
        self.assertTrue({"mode_get", "mode_set", "apply_approved_ado_change"}.isdisjoint(returned_calls))
        self.assertEqual(json.loads(response.text), proposal)
        stored = self.runtime.proposal_store.get(proposal["proposal_id"])
        self.assertEqual(stored.comment, "Validation proposal only")
        self.assertEqual(stored.expected_revision, 7)
        self.assertEqual(stored.status.value, "pending")
        self.reader.get_work_item.assert_awaited_once_with(6)
        self.assertEqual(self.writer.mock_calls, [])
        self.assertEqual(self.runtime.audit.list_events(), ())

    async def test_apply_pauses_for_separate_approval_and_denial_never_writes(self) -> None:
        proposal = self.runtime.proposals.stage_comment(6, 7, "Validation proposal only", "Validation")
        arguments = {"proposal_id": proposal.proposal_id, "digest": proposal.digest,
                     "change_summary": proposal.summary}
        model_calls = 0

        def respond(messages, options):
            nonlocal model_calls
            model_calls += 1
            if model_calls == 1:
                return Message("assistant", [Content.from_function_call(
                    call_id="apply", name="apply_approved_ado_change", arguments=arguments,
                )])
            result = next(c for m in messages for c in m.contents
                          if c.type == "function_result" and c.call_id == "apply")
            self.assertIn("rejected by user", str(result.result))
            return Message("assistant", ["Approval denied; no ADO change was made."])

        agent = create_mock_pmo_agent(ScriptedChatClient(respond), self.runtime)
        response = await agent.run("Submit this exact proposal for one-time approval.", session=self.session)
        requests = [c for m in response.messages for c in m.contents if c.type == "function_approval_request"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].function_call.name, "apply_approved_ado_change")
        self.assertEqual(requests[0].function_call.parse_arguments(), arguments)
        self.assertEqual(model_calls, 1)
        self.assertEqual(self.writer.mock_calls, [])
        denied = await agent.run(
            Message("user", [requests[0].to_function_approval_response(False)]), session=self.session,
        )
        self.assertIn("Approval denied", denied.text)
        self.assertEqual(model_calls, 2)
        self.assertEqual(self.writer.mock_calls, [])
        self.assertEqual(self.reader.mock_calls, [])
        self.assertEqual(proposal.status.value, "pending")
        self.assertEqual(self.runtime.audit.list_events(), ())


class SkillDefinitionTests(unittest.TestCase):
    def test_expected_skills_exist_with_matching_frontmatter_names(self) -> None:
        root = Path(__file__).resolve().parents[1] / "skills"
        expected = {
            "observe-task-board",
            "ask-task",
            "proposal-task-update",
            "update-task-board",
        }

        actual: set[str] = set()
        for path in root.glob("*/SKILL.md"):
            name_line = next(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("name:"))
            actual.add(name_line.partition(":")[2].strip())

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
