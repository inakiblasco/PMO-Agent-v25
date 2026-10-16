"""Tests for environment-backed PMO Agent configuration."""

from __future__ import annotations

import unittest

from fde_pmo_agent.settings import PmoSettings


class PmoSettingsTests(unittest.TestCase):
    def test_defaults_select_mock_runtime(self) -> None:
        settings = PmoSettings.from_mapping({})

        self.assertEqual(settings.runtime, "mock")
        self.assertEqual(settings.azure_credential_mode, "default")
        self.assertEqual(settings.cosmos_database_name, "fde-pmo-agent")
        self.assertIsNone(settings.foundry_project_endpoint)

    def test_foundry_runtime_requires_endpoint_and_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "FOUNDRY_PROJECT_ENDPOINT"):
            PmoSettings.from_mapping({"PMO_RUNTIME": "foundry"})

    def test_foundry_runtime_accepts_required_configuration(self) -> None:
        settings = PmoSettings.from_mapping(
            {
                "PMO_RUNTIME": "foundry",
                "FOUNDRY_PROJECT_ENDPOINT": "https://project.services.ai.azure.com",
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
                "COSMOS_ENDPOINT": "https://account.documents.azure.com:443/",
            }
        )

        self.assertEqual(settings.runtime, "foundry")
        self.assertEqual(settings.azure_ai_model_deployment_name, "gpt-4.1-mini")

    def test_unknown_runtime_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "PMO_RUNTIME"):
            PmoSettings.from_mapping({"PMO_RUNTIME": "production"})

    def test_azure_credential_mode_is_normalized(self) -> None:
        settings = PmoSettings.from_mapping({"AZURE_CREDENTIAL_MODE": " CLI "})

        self.assertEqual(settings.azure_credential_mode, "cli")

    def test_unknown_azure_credential_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "AZURE_CREDENTIAL_MODE"):
            PmoSettings.from_mapping({"AZURE_CREDENTIAL_MODE": "interactive"})
