"""Environment-backed configuration for local and Foundry runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv


def _optional(values: Mapping[str, str], name: str) -> str | None:
    value = values.get(name, "").strip()
    return value or None


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name, str(default)).strip().casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


@dataclass(frozen=True, slots=True)
class PmoSettings:
    """Non-secret PMO Agent configuration read from process environment."""

    runtime: str
    log_level: str
    skills_dir: str | None
    trace_enabled: bool
    trace_dir: str
    trace_max_chars: int
    foundry_project_endpoint: str | None
    azure_ai_model_deployment_name: str | None
    azure_credential_mode: str
    cosmos_endpoint: str | None
    cosmos_database_name: str
    cosmos_proposals_container: str
    cosmos_audit_container: str
    cosmos_message_delivery_container: str
    ado_mcp_server_url: str | None
    workiq_mcp_server_url: str | None
    m365_message_gateway_url: str | None
    applicationinsights_connection_string: str | None
    ado_mode: str = "mock"
    ado_toolbox_endpoint: str | None = None
    ado_project: str | None = None
    ado_query_id: str | None = None
    ado_due_date_field: str | None = None
    ado_completed_states: tuple[str, ...] = ()
    ado_server_label: str = "ado"
    ado_write_toolbox_endpoint: str | None = None
    workiq_mode: str = "disabled"
    workiq_toolbox_endpoint: str | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> PmoSettings:
        """Validate and construct settings without exposing secret values."""
        runtime = values.get("PMO_RUNTIME", "mock").strip().lower()
        if runtime not in {"mock", "foundry"}:
            raise ValueError("PMO_RUNTIME must be either 'mock' or 'foundry'.")

        azure_credential_mode = values.get("AZURE_CREDENTIAL_MODE", "default").strip().lower() or "default"
        if azure_credential_mode not in {"default", "cli", "azd", "managed_identity"}:
            raise ValueError("AZURE_CREDENTIAL_MODE must be 'default', 'cli', 'azd', or 'managed_identity'.")

        try:
            trace_max_chars = int(values.get("PMO_TRACE_MAX_CHARS", "20000"))
        except ValueError as exc:
            raise ValueError("PMO_TRACE_MAX_CHARS must be an integer.") from exc
        if trace_max_chars < 256:
            raise ValueError("PMO_TRACE_MAX_CHARS must be at least 256.")

        settings = cls(
            runtime=runtime,
            log_level=values.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
            skills_dir=_optional(values, "PMO_SKILLS_DIR"),
            trace_enabled=_boolean(values, "PMO_TRACE_ENABLED", True),
            trace_dir=values.get("PMO_TRACE_DIR", "log").strip() or "log",
            trace_max_chars=trace_max_chars,
            foundry_project_endpoint=_optional(values, "FOUNDRY_PROJECT_ENDPOINT"),
            azure_ai_model_deployment_name=_optional(values, "AZURE_AI_MODEL_DEPLOYMENT_NAME"),
            azure_credential_mode=azure_credential_mode,
            cosmos_endpoint=_optional(values, "COSMOS_ENDPOINT"),
            cosmos_database_name=values.get("COSMOS_DATABASE_NAME", "fde-pmo-agent").strip()
            or "fde-pmo-agent",
            cosmos_proposals_container=values.get("COSMOS_PROPOSALS_CONTAINER", "pmo-proposals").strip()
            or "pmo-proposals",
            cosmos_audit_container=values.get("COSMOS_AUDIT_CONTAINER", "pmo-audit-events").strip()
            or "pmo-audit-events",
            cosmos_message_delivery_container=values.get(
                "COSMOS_MESSAGE_DELIVERY_CONTAINER", "pmo-message-delivery"
            ).strip()
            or "pmo-message-delivery",
            ado_mcp_server_url=_optional(values, "ADO_MCP_SERVER_URL"),
            workiq_mcp_server_url=_optional(values, "WORKIQ_MCP_SERVER_URL"),
            m365_message_gateway_url=_optional(values, "M365_MESSAGE_GATEWAY_URL"),
            applicationinsights_connection_string=_optional(values, "APPLICATIONINSIGHTS_CONNECTION_STRING"),
            ado_mode=values.get("ADO_MODE", "mock").strip().lower(),
            ado_toolbox_endpoint=_optional(values, "ADO_TOOLBOX_ENDPOINT"),
            ado_project=_optional(values, "ADO_PROJECT"),
            ado_query_id=_optional(values, "ADO_QUERY_ID"),
            ado_due_date_field=_optional(values, "ADO_DUE_DATE_FIELD"),
            ado_completed_states=tuple(s.strip() for s in values.get("ADO_COMPLETED_STATES", "").split(",") if s.strip()),
            ado_server_label=values.get("ADO_SERVER_LABEL", "ado").strip(),
            ado_write_toolbox_endpoint=_optional(values, "ADO_WRITE_TOOLBOX_ENDPOINT"),
            workiq_mode=values.get("WORKIQ_MODE", "disabled").strip().lower(),
            workiq_toolbox_endpoint=_optional(values, "WORKIQ_TOOLBOX_ENDPOINT"),
        )
        settings._validate_runtime_requirements()
        return settings

    def _validate_runtime_requirements(self) -> None:
        if self.workiq_mode not in {"disabled", "toolbox"}:
            raise ValueError("WORKIQ_MODE must be 'disabled' or 'toolbox'.")
        if self.workiq_mode == "toolbox":
            self.workiq_toolbox_config()
            if self.ado_mode == "mock":
                raise ValueError("Real WorkIQ requires real ADO project validation.")
        if self.ado_mode not in {"mock", "toolbox_readonly", "toolbox"}:
            raise ValueError("ADO_MODE must be 'mock', 'toolbox_readonly', or 'toolbox'.")
        if self.ado_mode in {"toolbox_readonly", "toolbox"}:
            self.ado_toolbox_config()
        if self.ado_mode == "toolbox":
            self.ado_toolbox_config(write=True)
        if self.runtime != "foundry":
            return
        missing = [
            name
            for name, value in {
                "FOUNDRY_PROJECT_ENDPOINT": self.foundry_project_endpoint,
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": self.azure_ai_model_deployment_name,
            }.items()
            if value is None
        ]
        if missing:
            raise ValueError(f"PMO_RUNTIME=foundry requires: {', '.join(missing)}")

    def ado_toolbox_config(self, *, write: bool = False):
        """Construct validated, non-secret ADO connection settings."""
        from .integrations.mcp.ado import AdoToolboxConfig

        return AdoToolboxConfig(
            endpoint=(self.ado_write_toolbox_endpoint if write else self.ado_toolbox_endpoint) or "",
            project=self.ado_project or "",
            query_id=self.ado_query_id or "", due_date_field=self.ado_due_date_field or "",
            completed_states=self.ado_completed_states, server_label=self.ado_server_label,
        )

    def workiq_toolbox_config(self):
        from .integrations.mcp.workiq import WorkIqToolboxConfig

        return WorkIqToolboxConfig(endpoint=self.workiq_toolbox_endpoint or "")


def load_settings() -> PmoSettings:
    """Load a local .env without replacing environment values injected by Foundry."""
    load_dotenv(override=False)
    return PmoSettings.from_mapping(os.environ)
