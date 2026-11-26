#!/usr/bin/env python3
"""Tests for the mine-scene-interaction contract validator."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_interactions  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class InteractionValidationTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_fixture("interaction_contract.json")
        self.bindings = load_fixture("bindings.json")

    def codes(self, entries: list[dict]) -> set[str]:
        return {entry["code"] for entry in entries}

    def test_valid_contract_and_bindings_pass(self):
        report = validate_interactions.validate_interactions(self.contract, self.bindings)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["summary"]["handlers"], 6)
        self.assertEqual(report["summary"]["panels"], 3)
        self.assertEqual(report["summary"]["permissionRules"], 4)
        self.assertEqual(report["summary"]["eventChannels"], 1)
        self.assertEqual(report["summary"]["entities"], 4)
        self.assertEqual(report["summary"]["bindings"], 4)
        self.assertTrue(report["bindings"]["provided"])

    def test_unknown_handler_type_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["handlers"][0]["type"] = "explode"

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNKNOWN_HANDLER_TYPE", self.codes(report["errors"]))

    def test_unknown_entity_type_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["handlers"][4]["panels"][0]["entityType"] = "ROBOT"

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNKNOWN_ENTITY_TYPE", self.codes(report["errors"]))

    def test_missing_permission_rules_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["permissionRules"] = []

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("MISSING_PERMISSION_RULES", self.codes(report["errors"]))

    def test_missing_track_permission_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["permissionRules"] = [
            rule for rule in contract["permissionRules"] if rule["action"] != "VIEW_TRACK"
        ]

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertIn("MISSING_TRACK_PERMISSION", self.codes(report["errors"]))

    def test_unknown_permission_action_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["permissionRules"][0]["action"] = "VIEW_SECRET"

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertIn("UNKNOWN_PERMISSION_ACTION", self.codes(report["errors"]))

    def test_empty_channel_name_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["eventChannels"][0]["name"] = "  "

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertIn("MISSING_CHANNEL_NAME", self.codes(report["errors"]))

    def test_unknown_binding_entity_fails(self):
        bindings = copy.deepcopy(self.bindings)
        bindings["bindings"].append(
            {
                "bindingId": "BIND-PERSON-999",
                "entityId": "PERSON-999",
                "entityType": "PERSON",
                "objectId": "SCENE-OBJECT-999",
            }
        )

        report = validate_interactions.validate_interactions(self.contract, bindings)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNKNOWN_ENTITY_ID", self.codes(report["errors"]))

    def test_duplicate_handler_id_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["handlers"][1]["id"] = "pick-default"

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertIn("DUPLICATE_HANDLER_ID", self.codes(report["errors"]))

    def test_unknown_channel_reference_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["handlers"][5]["channelId"] = "missing-channel"

        report = validate_interactions.validate_interactions(contract, self.bindings)

        self.assertIn("UNKNOWN_CHANNEL_REF", self.codes(report["errors"]))

    def test_markdown_renderer(self):
        report = validate_interactions.validate_interactions(self.contract, self.bindings)
        markdown = validate_interactions.render_markdown(report)

        self.assertIn("# Scene Interaction Validation Report", markdown)
        self.assertIn("Permission Rules", markdown)
        self.assertIn("mine.twin.events", markdown)

    def test_write_outputs(self):
        report = validate_interactions.validate_interactions(self.contract, self.bindings)
        with tempfile.TemporaryDirectory() as tmp:
            paths = validate_interactions.write_outputs(
                report,
                str(Path(tmp) / "interaction_validation.json"),
                str(Path(tmp) / "interaction_validation.md"),
            )
            written = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

        self.assertEqual(written["status"], "PASS")
        self.assertIn("# Scene Interaction Validation Report", markdown)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "interaction_validation.json")
            markdown = str(Path(tmp) / "interaction_validation.md")
            ok = validate_interactions.main(
                [
                    str(FIXTURES / "interaction_contract.json"),
                    "--bindings",
                    str(FIXTURES / "bindings.json"),
                    "--output",
                    output,
                    "--markdown",
                    markdown,
                ]
            )
            self.assertEqual(ok, 0)
            self.assertTrue(Path(output).exists())

            invalid_contract = copy.deepcopy(self.contract)
            invalid_contract["permissionRules"] = []
            invalid_path = Path(tmp) / "invalid_contract.json"
            invalid_path.write_text(json.dumps(invalid_contract), encoding="utf-8")

            failed = validate_interactions.main(
                [
                    str(invalid_path),
                    "--bindings",
                    str(FIXTURES / "bindings.json"),
                    "--output",
                    output,
                    "--markdown",
                    markdown,
                ]
            )
            self.assertEqual(failed, 1)

            no_fail = validate_interactions.main(
                [
                    str(invalid_path),
                    "--bindings",
                    str(FIXTURES / "bindings.json"),
                    "--output",
                    output,
                    "--markdown",
                    markdown,
                    "--no-fail",
                ]
            )
            self.assertEqual(no_fail, 0)


if __name__ == "__main__":
    unittest.main()
