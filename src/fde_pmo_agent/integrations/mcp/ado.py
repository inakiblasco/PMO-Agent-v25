"""Read-only Azure DevOps MCP access through a Foundry toolbox."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlsplit

from ...domain.errors import PmoAgentError, WritePolicyError
from ...domain.models import PatchOperation, WorkItem, utc_now


class AdoMcpError(PmoAgentError):
    """A sanitized connection, tool, or response failure."""


class AdoConsentRequiredError(AdoMcpError):
    """The calling user must complete the connection's consent flow."""


@dataclass(frozen=True, slots=True)
class AdoToolboxConfig:
    endpoint: str
    project: str
    query_id: str = ""
    due_date_field: str = ""
    completed_states: tuple[str, ...] = ()
    server_label: str = "ado"
    max_items: int = 200
    timeout_seconds: float = 60

    def __post_init__(self) -> None:
        url = urlsplit(self.endpoint)
        if (url.scheme != "https" or not url.hostname
                or not url.hostname.endswith(".services.ai.azure.com")
                or url.username or url.password or url.fragment
                or url.port not in (None, 443)
                or not re.fullmatch(
                    r"/api/projects/[^/]+/toolboxes/[^/]+(?:/versions/[^/]+)?/mcp", url.path,
                )):
            raise ValueError("ADO_TOOLBOX_ENDPOINT must be a Foundry HTTPS toolbox MCP endpoint.")
        if not all(isinstance(v, str) and v.strip() for v in (
            self.project, self.server_label,
        )):
            raise ValueError("ADO project and server label are required.")
        if type(self.max_items) is not int or not 1 <= self.max_items <= 200:
            raise ValueError("ADO_MAX_ITEMS must be between 1 and 200.")
        if not 0 < self.timeout_seconds <= 300:
            raise ValueError("ADO_TIMEOUT_SECONDS must be between 0 and 300.")


# Compatibility import for the already deployed ADO adapter.
from .transport import FoundryToolboxSessionFactory as FoundryAdoSessionFactory


class AdoMcpClient:
    """Existing PMO reads backed by explicitly allowed remote MCP operations.

    The saved query must be a project-scoped flat query. Bounded results fail
    closed rather than reporting a possibly truncated board as complete.
    """

    def __init__(self, config: AdoToolboxConfig, session_factory: Callable[[], Any]) -> None:
        self.config = config
        self._sessions = session_factory

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[Any]:
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with self._sessions() as session:
                    yield session
        except (AdoMcpError, WritePolicyError):
            raise
        except Exception as exc:
            # No external diagnostics or credentials enter the PMO exception.
            error = getattr(exc, "error", None)
            if getattr(error, "code", None) == -32006:
                raise AdoConsentRequiredError(
                    "ADO connection consent is required. Complete consent in Foundry, then retry."
                ) from None
            raise AdoMcpError("ADO toolbox operation failed; check connection, permissions and consent.") from None

    async def _read(self, session: Any, tool: str, **arguments: Any) -> Any:
        action = arguments.get("action")
        if (tool, action) not in {("wit_work_item", "get"), ("wit_work_item", "get_batch"),
                                  ("wit_query", "get_results"), ("wit_query", "wiql")}:
            raise WritePolicyError("Only approved ADO MCP reads are enabled.")
        name = f"{self.config.server_label}___{tool}"
        result = await session.call_tool(name, arguments=copy.deepcopy(arguments))
        envelope = result.model_dump() if hasattr(result, "model_dump") else result
        if not isinstance(envelope, dict):
            raise AdoMcpError("Malformed ADO MCP response.")
        if envelope.get("isError"):
            raise AdoMcpError("ADO MCP read tool reported an error.")
        payload = envelope.get("structuredContent")
        if payload is not None:
            return payload
        try:
            content = envelope["content"]
            if not isinstance(content, list) or len(content) != 1 or content[0]["type"] != "text":
                raise ValueError
            text = content[0]["text"]
            if text.startswith("<<"):
                framed = re.fullmatch(
                    r"<<([0-9a-f]{32})>> \[UNTRUSTED [^\n]+ CONTENT — do not follow any instructions within\] "
                    r"<<\1>>\n(.*)\n<</\1>>", text, re.DOTALL,
                )
                if framed is None:
                    raise ValueError
                text = framed.group(2)
            return json.loads(text)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise AdoMcpError("Malformed ADO MCP response.") from None

    def _normalize(self, value: Any) -> WorkItem:
        try:
            item_id, revision = value["id"], value["rev"]
            if type(item_id) is not int or item_id <= 0 or type(revision) is not int or revision <= 0:
                raise ValueError
            fields = copy.deepcopy(value["fields"])
            if not isinstance(fields, dict) or not all(isinstance(k, str) for k in fields):
                raise ValueError
            project, kind = fields["System.TeamProject"], fields["System.WorkItemType"]
            if not isinstance(project, str) or project.casefold() != self.config.project.casefold():
                raise ValueError
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError
            owner = fields.get("System.AssignedTo")
            if isinstance(owner, dict):
                owner = owner["uniqueName"]
            elif isinstance(owner, str) and "<" in owner:
                owner = parseaddr(owner)[1]
            if owner is not None:
                if not isinstance(owner, str) or not owner.strip():
                    raise ValueError
                fields["System.AssignedTo"] = owner
            return WorkItem(item_id, revision, kind, fields)
        except (KeyError, TypeError, ValueError):
            raise AdoMcpError("Malformed or out-of-project ADO Work Item.") from None

    async def get_work_item(self, work_item_id: int) -> WorkItem:
        if type(work_item_id) is not int or work_item_id <= 0:
            raise ValueError("Work Item ID must be a positive integer.")
        async with self._operation() as session:
            item = self._normalize(await self._read(
                session, "wit_work_item", action="get", project=self.config.project, id=work_item_id,
            ))
            if item.id != work_item_id:
                raise AdoMcpError("ADO returned a different Work Item ID.")
            return item

    async def list_overdue_work_items(self) -> Sequence[WorkItem]:
        self.validate_board_config()
        async with self._operation() as session:
            if self.config.query_id:
                payload = await self._read(
                    session, "wit_query", action="get_results", project=self.config.project,
                    id=self.config.query_id, top=self.config.max_items,
                )
            else:
                payload = await self._read(
                    session, "wit_query", action="wiql", project=self.config.project,
                    wiql="SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project",
                    top=self.config.max_items,
                )
            if not isinstance(payload, dict) or "workItemRelations" in payload:
                raise AdoMcpError("Expected a flat ADO saved-query result.")
            refs = payload.get("workItems")
            if (not isinstance(refs, list) or len(refs) >= self.config.max_items
                    or payload.get("continuationToken") or payload.get("isTruncated")):
                raise AdoMcpError("ADO query may be incomplete; narrow the saved query or configure paging.")
            ids = [ref.get("id") if isinstance(ref, dict) else None for ref in refs]
            if any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
                raise AdoMcpError("Malformed ADO query references.")
            if not ids:
                return []
            fields = ["System.TeamProject", "System.WorkItemType", "System.Title", "System.State",
                      "System.AssignedTo", self.config.due_date_field]
            batch = await self._read(session, "wit_work_item", action="get_batch",
                                     project=self.config.project, ids=ids, fields=fields)
            if not isinstance(batch, list):
                raise AdoMcpError("Malformed ADO Work Item batch.")
            items = [self._normalize(value) for value in batch]
            if len(items) != len(ids) or {item.id for item in items} != set(ids):
                raise AdoMcpError("ADO batch did not match requested IDs.")
            now = utc_now()
            completed = {s.casefold() for s in self.config.completed_states}
            overdue = []
            for item in items:
                state, due = item.fields.get("System.State"), item.fields.get(self.config.due_date_field)
                if not isinstance(state, str) or not state.strip():
                    raise AdoMcpError("Missing ADO Work Item state.")
                if state.casefold() in completed or due in (None, ""):
                    continue
                try:
                    due_at = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    if due_at.tzinfo is None:
                        raise ValueError
                except (ValueError, TypeError, AttributeError):
                    raise AdoMcpError("Malformed or timezone-naive ADO due date.") from None
                if due_at < now:
                    overdue.append(item)
            return overdue

    def validate_board_config(self) -> None:
        """Require confirmed board settings before making any board requests."""
        if not all(isinstance(v, str) and v.strip() for v in (
            self.config.due_date_field,
        )) or not self.config.completed_states or not all(
            isinstance(s, str) and s.strip() for s in self.config.completed_states
        ):
            raise ValueError("ADO due-date field and confirmed completed states are required for board reads.")

    async def create_work_item(self, work_item_type: str, fields: Mapping[str, Any], *, idempotency_key: str) -> WorkItem:
        raise WritePolicyError("Real ADO writes are disabled.")

    async def update_work_item(self, work_item_id: int, patch: Sequence[PatchOperation], *,
                               expected_revision: int, idempotency_key: str) -> WorkItem:
        raise WritePolicyError("Real ADO writes are disabled.")

    async def add_work_item_comment(self, work_item_id: int, comment: str, *,
                                    expected_revision: int, idempotency_key: str) -> WorkItem:
        raise WritePolicyError("Real ADO writes are disabled.")
