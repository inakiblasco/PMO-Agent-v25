"""Composition root for the mock PMO services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from threading import RLock
from collections.abc import Callable

from agent_framework import FunctionInvocationContext

from .domain.models import WorkItem, utc_now
from .domain.policy import AdoWritePolicy
from .integrations.mock.ado import MockAdoClient
from .integrations.mock.collaboration import MockMessageClient, MockWorkIqClient
from .workflows.ado_write_gateway import AdoWriteGateway
from .workflows.proposal_service import ProposalService
from .workflows.proposal_store import InMemoryAuditStore, InMemoryProposalStore
from .workflows.ports import AdoClient, WorkIqClient, MessageClient
from .domain.errors import MessagePolicyError


class DisabledWorkIqClient:
    async def search_task_context(self, work_item_id: int, query: str):
        raise MessagePolicyError("Real WorkIQ evidence is not connected.")


class DisabledMessageClient:
    async def send_task_status_request(self, **kwargs):
        raise MessagePolicyError("Real message sending is disabled.")


@dataclass(slots=True)
class PmoRuntime:
    """Session-owned PMO services with injectable external clients."""

    session_id: str
    ado: AdoClient
    workiq: WorkIqClient
    messages: MessageClient
    proposals: ProposalService
    write_gateway: AdoWriteGateway
    proposal_store: InMemoryProposalStore
    audit: InMemoryAuditStore

    @classmethod
    def readonly(cls, session_id: str, ado: AdoClient, *, writer: AdoClient | None = None,
                 due_date_field: str | None = None, workiq: WorkIqClient | None = None) -> PmoRuntime:
        audit = InMemoryAuditStore()
        store = InMemoryProposalStore()
        default_policy = AdoWritePolicy()
        extra_fields = frozenset({due_date_field}) if due_date_field else frozenset()
        policy = AdoWritePolicy(
            allowed_create_fields=default_policy.allowed_create_fields | extra_fields,
            allowed_update_fields=default_policy.allowed_update_fields | extra_fields,
        )
        return cls(
            session_id, ado, workiq or DisabledWorkIqClient(), DisabledMessageClient(),
            ProposalService(session_id, store, policy),
            AdoWriteGateway(session_id=session_id, client=writer or ado, proposals=store, audit=audit, policy=policy),
            store, audit,
        )


class MockPmoRuntime(PmoRuntime):
    """Mock factory retained for tests and local demos."""

    @classmethod
    def create(cls, session_id: str = "mock-session") -> MockPmoRuntime:
        audit = InMemoryAuditStore()
        proposal_store = InMemoryProposalStore()
        policy = AdoWritePolicy()
        overdue = (utc_now() - timedelta(days=2)).isoformat()
        ado = MockAdoClient(
            [
                WorkItem(
                    id=101,
                    revision=4,
                    work_item_type="Task",
                    fields={
                        "System.Title": "Prepare hackathon demo",
                        "System.State": "Active",
                        "System.AssignedTo": "alex@example.com",
                        "Microsoft.VSTS.Scheduling.DueDate": overdue,
                    },
                )
            ]
        )
        workiq = MockWorkIqClient(
            {
                101: [
                    {
                        "source_id": "teams-thread-42",
                        "source_type": "teams",
                        "observed_at": utc_now().isoformat(),
                        "summary": "The assignee reported that the demo is nearly complete.",
                    }
                ]
            }
        )
        messages = MockMessageClient(session_id=session_id, ado=ado, audit=audit)
        proposals = ProposalService(session_id, proposal_store, policy)
        write_gateway = AdoWriteGateway(
            session_id=session_id,
            client=ado,
            proposals=proposal_store,
            audit=audit,
            policy=policy,
        )
        return cls(session_id, ado, workiq, messages, proposals, write_gateway, proposal_store, audit)


class SessionRuntimeRegistry:
    """Own one injected PMO runtime per Agent Framework session.

    This is a process-local bridge used while the external adapters and Cosmos
    stores are still mocked. Missing Agent sessions fail closed so one hosted
    user's proposal state can never fall back to another user's runtime.
    """

    def __init__(self, factory: Callable[[str], PmoRuntime] = MockPmoRuntime.create) -> None:
        self._factory = factory
        self._items: dict[str, PmoRuntime] = {}
        self._lock = RLock()

    def resolve(self, context: FunctionInvocationContext) -> PmoRuntime:
        session_id = context.session.session_id if context.session is not None else None
        if not session_id:
            raise RuntimeError("Hosted PMO tools require an Agent Framework session ID.")
        with self._lock:
            runtime = self._items.get(session_id)
            if runtime is None:
                runtime = self._factory(session_id)
                self._items[session_id] = runtime
            return runtime

    def get(self, session_id: str) -> PmoRuntime | None:
        """Return an existing session runtime without creating it."""
        with self._lock:
            return self._items.get(session_id)
