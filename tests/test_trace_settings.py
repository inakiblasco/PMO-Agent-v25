"""Tests for execution trace settings."""

from __future__ import annotations

import unittest

from fde_pmo_agent.settings import PmoSettings


class TraceSettingsTests(unittest.TestCase):
    def test_trace_defaults_are_enabled(self) -> None:
        settings = PmoSettings.from_mapping({})

        self.assertTrue(settings.trace_enabled)
        self.assertEqual(settings.trace_dir, "log")
        self.assertEqual(settings.trace_max_chars, 20_000)

    def test_trace_settings_can_be_overridden(self) -> None:
        settings = PmoSettings.from_mapping(
            {
                "PMO_TRACE_ENABLED": "off",
                "PMO_TRACE_DIR": "custom-log",
                "PMO_TRACE_MAX_CHARS": "512",
            }
        )

        self.assertFalse(settings.trace_enabled)
        self.assertEqual(settings.trace_dir, "custom-log")
        self.assertEqual(settings.trace_max_chars, 512)

    def test_trace_max_chars_rejects_small_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 256"):
            PmoSettings.from_mapping({"PMO_TRACE_MAX_CHARS": "100"})


if __name__ == "__main__":
    unittest.main()
