"""Agent Framework tool adapters over the provider-neutral mock runtime."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from typing import Annotated, Any

from agent_framework import Content, FunctionInvocationContext, FunctionMiddleware, UserInputRequiredException, tool

from ..domain.models import PatchOperation
from ..runtime import PmoRuntime
from ..integrations.mcp.workiq import WorkIqConsentRequiredError


class WorkIqConsentMiddleware(FunctionMiddleware):
    """Pause outside FunctionTool.invoke so expected consent is not logged as failure."""

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        await call_next()
        if context.function.name != "workiq_search_task_context":
            return
        if isinstance(context.result, list):
            requests = [c for c in context.result if isinstance(c, Content) and c.type == "oauth_consent_request"]
            if requests:
                # Settle the original model call before pausing. Without this
                # tool output, the next turn is rejected as an unanswered call.
                waiting = Content.from_function_result(
                    call_id=str(context.metadata["call_id"]),
                    result={"status": "consent_required", "message": "WorkIQ is awaiting user consent; retrieval did not complete."},
                )
                raise UserInputRequiredException(contents=[waiting, *requests], message="WorkIQ requires user sign-in and consent.")


def _json_object(value: str, argument_name: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{argument_name} must be a JSON object.")
    return parsed


def _json_string_list(value: str, argument_name: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"{argument_name} must be a JSON array of strings.")
    return parsed


def _json_patch(value: str) -> list[PatchOperation]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("patch_json must be a JSON array.")
    operations: list[PatchOperation] = []
    for item in parsed:
        if not isinstance(item, dict) or not {"op", "path", "value"} <= set(item):
            raise ValueError("Each patch entry must contain op, path, and value.")
        operations.append(PatchOperation(str(item["op"]), str(item["path"]), item["value"]))
    return operations


def build_agent_tools(
    runtime: PmoRuntime,
    *,
    runtime_resolver: Callable[[FunctionInvocationContext], PmoRuntime] | None = None,
) -> list[Any]:
    """Build model-facing tools while keeping the raw ADO writer private."""

    def current_runtime(context: FunctionInvocationContext) -> PmoRuntime:
        return runtime_resolver(context) if runtime_resolver is not None else runtime

    @tool(name="ado_list_overdue_work_items", approval_mode="never_require")
    async def ado_list_overdue_work_items(context: FunctionInvocationContext) -> list[dict[str, Any]]:
        """List open ADO Work Items whose due date has passed."""
        active = current_runtime(context)
        return [item.to_dict() for item in await active.ado.list_overdue_work_items()]

    @tool(name="ado_get_work_item", approval_mode="never_require")
    async def ado_get_work_item(
        context: FunctionInvocationContext,
        work_item_id: Annotated[int, "ADO Work Item ID."],
    ) -> dict[str, Any]:
        """Get the latest ADO Work Item including its revision."""
        return (await current_runtime(context).ado.get_work_item(work_item_id)).to_dict()

    @tool(name="workiq_search_task_context", approval_mode="never_require")
    async def workiq_search_task_context(
        work_item_id: Annotated[int, "ADO Work Item ID used for correlation."],
        context: FunctionInvocationContext,
        query: Annotated[str, "Untrusted search criteria; blank uses the ADO title, assignee, and default lookback."],
    ) -> list[dict[str, Any]] | list[Content]:
        """Retrieve WorkIQ task context. Synthesized answers may contain unverified citations."""
        try:
            return [dict(item) for item in await current_runtime(context).workiq.search_task_context(work_item_id, query)]
        except WorkIqConsentRequiredError as exc:
            if exc.consent_link:
                return [Content.from_oauth_consent_request(
                    exc.consent_link, additional_properties={"server_label": "WorkIQ"},
                )]
            result = {"status": "consent_required", "work_item_id": work_item_id,
                      "message": "WorkIQ の同意が必要ですがリンクを取得できませんでした。Foundry の WorkIQ Connection を確認してください。"}
            return [result]

    @tool(name="send_task_status_request", approval_mode="never_require")
    async def send_task_status_request(
        work_item_id: Annotated[int, "ADO Work Item ID."],
        recipient: Annotated[str, "Recipient UPN; must match the current ADO assignee."],
        context: FunctionInvocationContext,
        message: Annotated[str, "Task status request sent through Autopilot or Microsoft 365."],
    ) -> dict[str, Any]:
        """Send a task-status request without approval, subject to delivery policy."""
        key_input = f"{work_item_id}\0{recipient.casefold()}\0{message.strip()}"
        key = hashlib.sha256(key_input.encode()).hexdigest()
        return dict(
            await current_runtime(context).messages.send_task_status_request(
                work_item_id=work_item_id,
                recipient=recipient,
                message=message,
                idempotency_key=key,
            )
        )

    @tool(name="propose_work_item_create", approval_mode="never_require")
    def propose_work_item_create(
        work_item_type: Annotated[str, "Task, Bug, User Story, or Product Backlog Item."],
        fields_json: Annotated[str, "JSON object of ADO field reference names and proposed values."],
        reason: Annotated[str, "Why the Work Item should be created."],
        context: FunctionInvocationContext,
        evidence_json: Annotated[str, "JSON array of supporting source IDs."] = "[]",
    ) -> dict[str, Any]:
        """Stage a Work Item creation proposal without writing to ADO."""
        proposal = current_runtime(context).proposals.stage_create(
            work_item_type,
            _json_object(fields_json, "fields_json"),
            reason,
            evidence=_json_string_list(evidence_json, "evidence_json"),
        )
        return proposal.to_public_dict()

    @tool(name="propose_work_item_update", approval_mode="never_require")
    def propose_work_item_update(
        work_item_id: Annotated[int, "ADO Work Item ID."],
        expected_revision: Annotated[int, "Current ADO revision returned by ado_get_work_item."],
        patch_json: Annotated[str, "JSON array of op, path, and value entries."],
        reason: Annotated[str, "Why these fields should change."],
        context: FunctionInvocationContext,
        evidence_json: Annotated[str, "JSON array of supporting source IDs."] = "[]",
    ) -> dict[str, Any]:
        """Stage a field update proposal without writing to ADO."""
        proposal = current_runtime(context).proposals.stage_update(
            work_item_id,
            expected_revision,
            _json_patch(patch_json),
            reason,
            evidence=_json_string_list(evidence_json, "evidence_json"),
        )
        return proposal.to_public_dict()

    @tool(name="propose_work_item_comment", approval_mode="never_require")
    def propose_work_item_comment(
        context: FunctionInvocationContext,
        work_item_id: Annotated[int, "ADO Work Item ID."],
        expected_revision: Annotated[int, "Current ADO revision returned by ado_get_work_item."],
        comment: Annotated[str, "Comment proposed for the Work Item."],
        reason: Annotated[str, "Why the comment should be added."],
        evidence_json: Annotated[str, "JSON array of supporting source IDs."] = "[]",
    ) -> dict[str, Any]:
        """Stage a Work Item comment proposal without writing to ADO."""
        proposal = current_runtime(context).proposals.stage_comment(
            work_item_id,
            expected_revision,
            comment,
            reason,
            evidence=_json_string_list(evidence_json, "evidence_json"),
        )
        return proposal.to_public_dict()

    @tool(name="apply_approved_ado_change", approval_mode="always_require")
    async def apply_approved_ado_change(
        proposal_id: Annotated[str, "Proposal ID returned by a propose tool."],
        context: FunctionInvocationContext,
        digest: Annotated[str, "Exact proposal digest returned by the propose tool."],
        change_summary: Annotated[str, "Exact human-readable summary returned by the propose tool."],
    ) -> dict[str, object]:
        """Apply an exact staged proposal through the private ADO write gateway."""
        return await current_runtime(context).write_gateway.apply(proposal_id, digest, change_summary)

    return [
        ado_list_overdue_work_items,
        ado_get_work_item,
        workiq_search_task_context,
        send_task_status_request,
        propose_work_item_create,
        propose_work_item_update,
        propose_work_item_comment,
        apply_approved_ado_change,
    ]
