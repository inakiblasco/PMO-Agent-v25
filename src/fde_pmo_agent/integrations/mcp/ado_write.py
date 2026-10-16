"""Private, approval-bound ADO writer using revision-guarded MCP updates."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.errors import RevisionConflictError, WriteOutcomeUnknownError, WritePolicyError
from ...domain.models import PatchOperation, WorkItem
from .ado import AdoMcpClient, AdoMcpError


class AdoWriteMcpClient(AdoMcpClient):
    """Only the Gateway receives this client; raw write tools stay private.

    No retries or server-side idempotency are assumed. An error after dispatch
    requires reconciliation; the Gateway consumes the proposal in that case.
    """

    async def _write(self, *, arguments: dict[str, Any], expected_id: int | None = None,
                     expected_revision: int | None = None) -> WorkItem:
        dispatched = False
        try:
            async with self._operation() as session:
                # Confirm the current tool contract before crossing the write boundary.
                tools = await session.list_tools()
                name = f"{self.config.server_label}___wit_work_item_write"
                schema = next((t.inputSchema for t in tools.tools if t.name == name), None)
                if schema is None or not set(arguments) <= schema.get("properties", {}).keys():
                    raise WritePolicyError("ADO Toolbox does not expose the required write contract.")
                dispatched = True
                result = await session.call_tool(name, arguments=copy.deepcopy(arguments))
                envelope = result.model_dump() if hasattr(result, "model_dump") else result
                if not isinstance(envelope, dict) or envelope.get("isError"):
                    raise AdoMcpError("ADO write returned an error.")
                payload = envelope.get("structuredContent")
                if payload is None:
                    content = envelope["content"]
                    if len(content) != 1 or content[0]["type"] != "text":
                        raise AdoMcpError("Malformed ADO write response.")
                    payload = json.loads(content[0]["text"])
                item = self._normalize(payload)
                if expected_id is not None and item.id != expected_id:
                    raise AdoMcpError("ADO write returned another Work Item.")
                if expected_revision is not None and item.revision != expected_revision + 1:
                    raise AdoMcpError("ADO write did not return the expected revision.")
                if arguments["action"] == "create":
                    if item.work_item_type != arguments["workItemType"]:
                        raise AdoMcpError("ADO created another Work Item type.")
                    if item.fields.get("System.Title") != next(
                        (f["value"] for f in arguments["fields"] if f["name"] == "System.Title"), None,
                    ):
                        raise AdoMcpError("ADO create result did not match the approved title.")
                else:
                    for update in arguments["updates"][1:]:
                        field = update["path"].removeprefix("/fields/")
                        if field == "System.History":
                            continue  # ADO can HTML-normalize discussion text.
                        if field in {"System.Title", "System.State", "System.Tags"} and item.fields.get(field) != update["value"]:
                            raise AdoMcpError("ADO update result did not match the approved field.")
                return item
        except asyncio.CancelledError:
            raise
        except Exception:
            if dispatched:
                raise WriteOutcomeUnknownError(
                    "ADO write outcome is unconfirmed. Check ADO and audit before creating a new proposal; "
                    "this proposal will not be retried."
                ) from None
            raise

    @staticmethod
    def _validate_key(idempotency_key: str) -> None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise WritePolicyError("A proposal ID is required for ADO writes.")

    async def create_work_item(self, work_item_type: str, fields: Mapping[str, Any], *,
                               idempotency_key: str) -> WorkItem:
        self._validate_key(idempotency_key)
        return await self._write(arguments={
            "action": "create", "project": self.config.project, "workItemType": work_item_type,
            "fields": [{"name": k, "value": copy.deepcopy(v)} for k, v in fields.items()],
        })

    async def update_work_item(self, work_item_id: int, patch: Sequence[PatchOperation], *,
                               expected_revision: int, idempotency_key: str) -> WorkItem:
        self._validate_key(idempotency_key)
        if type(work_item_id) is not int or work_item_id <= 0 or type(expected_revision) is not int or expected_revision <= 0:
            raise WritePolicyError("Positive Work Item ID and revision are required.")
        if not patch or any(p.op not in {"add", "replace"} or not p.path.startswith("/fields/") for p in patch):
            raise WritePolicyError("Only field additions and replacements are supported.")
        current = await self.get_work_item(work_item_id)
        if current.revision != expected_revision:
            raise RevisionConflictError("ADO Work Item changed; obtain a new proposal and approval.")
        updates = [{"op": "Test", "path": "/rev", "value": expected_revision}]
        updates.extend({"op": p.op.title(), "path": p.path, "value": copy.deepcopy(p.value)} for p in patch)
        return await self._write(arguments={
            "action": "update", "project": self.config.project, "id": work_item_id, "updates": updates,
        }, expected_id=work_item_id, expected_revision=expected_revision)

    async def add_work_item_comment(self, work_item_id: int, comment: str, *,
                                    expected_revision: int, idempotency_key: str) -> WorkItem:
        # Dedicated comments MCP cannot enforce revision. History appends discussion
        # with the same atomic /rev guard used for all field updates.
        if not isinstance(comment, str) or not comment.strip() or len(comment) > 4000:
            raise WritePolicyError("ADO comments must contain 1 to 4000 characters.")
        result = await self.update_work_item(
            work_item_id, [PatchOperation("add", "/fields/System.History", comment)],
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )
        result.comments.append(comment)
        return result
