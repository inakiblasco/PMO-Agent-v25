"""Run the PMO HarnessAgent with mock or read-only ADO toolbox services."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import AzureCliCredential, AzureDeveloperCliCredential, DefaultAzureCredential, ManagedIdentityCredential

from ..agent.factory import SKILLS_DIR, create_mock_pmo_agent
from ..agent.tracing import ExecutionTraceRecorder
from ..runtime import MockPmoRuntime, PmoRuntime, SessionRuntimeRegistry
from ..settings import PmoSettings, load_settings

def create_azure_credential(settings: PmoSettings) -> Any:
    """Create the explicitly configured Azure credential chain."""
    if settings.azure_credential_mode == "cli":
        return AzureCliCredential()
    if settings.azure_credential_mode == "azd":
        return AzureDeveloperCliCredential()
    if settings.azure_credential_mode == "managed_identity":
        return ManagedIdentityCredential()
    return DefaultAzureCredential()



def create_foundry_agent(
    settings: PmoSettings,
    *,
    credential: Any | None = None,
    client_factory: Callable[..., Any] = FoundryChatClient,
    runtime_registry: SessionRuntimeRegistry | None = None,
) -> Agent:
    """Create a Foundry-backed HarnessAgent with session-isolated PMO tools."""
    if settings.runtime != "foundry":
        raise ValueError("PMO_RUNTIME must be 'foundry' when starting the Foundry host.")
    if settings.foundry_project_endpoint is None or settings.azure_ai_model_deployment_name is None:
        raise ValueError("Foundry endpoint and model deployment are required.")

    active_credential = credential if credential is not None else create_azure_credential(settings)
    client = client_factory(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.azure_ai_model_deployment_name,
        credential=active_credential,
    )
    if settings.ado_mode in {"toolbox_readonly", "toolbox"}:
        from ..integrations.mcp.ado import AdoMcpClient, FoundryAdoSessionFactory

        config = settings.ado_toolbox_config()
        ado = AdoMcpClient(config, FoundryAdoSessionFactory(config, active_credential))
        workiq = None
        if settings.workiq_mode == "toolbox":
            from ..integrations.mcp.workiq import WorkIqToolboxClient
            from ..integrations.mcp.transport import FoundryToolboxSessionFactory

            workiq_config = settings.workiq_toolbox_config()
            workiq = WorkIqToolboxClient(
                workiq_config, FoundryToolboxSessionFactory(workiq_config, active_credential), ado,
            )
        writer = None
        if settings.ado_mode == "toolbox":
            from ..integrations.mcp.ado_write import AdoWriteMcpClient

            write_config = settings.ado_toolbox_config(write=True)
            writer = AdoWriteMcpClient(write_config, FoundryAdoSessionFactory(write_config, active_credential))
        registry = runtime_registry or SessionRuntimeRegistry(lambda sid: PmoRuntime.readonly(
            sid, ado, writer=writer, due_date_field=config.due_date_field, workiq=workiq,
        ))
    else:
        registry = runtime_registry or SessionRuntimeRegistry()
    bootstrap_runtime = (
        PmoRuntime.readonly("host-bootstrap", ado)
        if settings.ado_mode in {"toolbox_readonly", "toolbox"}
        else MockPmoRuntime.create("host-bootstrap")
    )
    skills_dir = Path(settings.skills_dir) if settings.skills_dir else SKILLS_DIR
    trace_recorder = (
        ExecutionTraceRecorder(settings.trace_dir, max_chars=settings.trace_max_chars)
        if settings.trace_enabled and settings.ado_mode == "mock"
        else None
    )
    return create_mock_pmo_agent(
        client,
        bootstrap_runtime,
        runtime_resolver=registry.resolve,
        default_options={"store": False},
        skills_dir=skills_dir,
        trace_recorder=trace_recorder,
    )


def create_foundry_host(
    settings: PmoSettings,
    *,
    credential: Any | None = None,
    client_factory: Callable[..., Any] = FoundryChatClient,
    server_factory: Callable[..., Any] = ResponsesHostServer,
) -> Any:
    """Create the Responses API host without starting its blocking event loop."""
    agent = create_foundry_agent(settings, credential=credential, client_factory=client_factory)
    return server_factory(agent, history_source="agent")


def main() -> None:
    """Load configuration and run the Foundry Responses host."""
    settings = load_settings()
    logging.basicConfig(level=settings.log_level)
    server = create_foundry_host(settings)
    server.run()


if __name__ == "__main__":
    main()
