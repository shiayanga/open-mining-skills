#!/usr/bin/env python3
"""Tests for the mine-iot-integration event validator."""

from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import validate_events  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class EventValidationTests(unittest.TestCase):
    def setUp(self):
        self.mapping = validate_events.read_json(FIXTURES / "device_mapping.json")
        self.events = copy.deepcopy(validate_events.read_jsonl(FIXTURES / "events.jsonl"))

    def codes(self, report):
        return {issue["code"] for issue in report["issues"]}

    def test_valid_events_pass(self):
        report = validate_events.validate_events(self.mapping, self.events)

        self.assertEqual(report["status"], "PASS")
        summary = report["summary"]
        self.assertEqual(summary["mapping_entries"], 3)
        self.assertEqual(summary["devices_mapped"], 3)
        self.assertEqual(summary["entities_mapped"], 3)
        self.assertEqual(summary["events_total"], 4)
        self.assertEqual(summary["valid_events"], 4)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 0)
        self.assertEqual(summary["event_types"]["ENTITY_POSITION_UPDATE"], 3)
        self.assertEqual(summary["event_types"]["MONITOR_VALUE_UPDATE"], 1)
        self.assertEqual(summary["position_qualities"]["VALID"], 2)
        self.assertEqual(summary["position_qualities"]["LOW_ACCURACY"], 1)
        self.assertEqual(summary["latest_entities"], 3)

        person = next(
            item for item in report["latest_by_entity"] if item["entityId"] == "PERSON-001"
        )
        self.assertEqual(person["sourceTimestamp"], 1795680003000)
        self.assertEqual(person["sequence"], 2)
        self.assertEqual(person["sourceDeviceId"], "TL-1001")

    def test_unknown_device_fails(self):
        self.events[0]["payload"]["sourceDeviceId"] = "TL-9999"
        report = validate_events.validate_events(self.mapping, self.events)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNKNOWN_DEVICE", self.codes(report))
        self.assertEqual(report["summary"]["unknown_device_ids"], ["TL-9999"])
        self.assertEqual(report["summary"]["valid_events"], 3)
        message = next(
            issue["message"] for issue in report["issues"] if issue["code"] == "UNKNOWN_DEVICE"
        )
        self.assertIn("TL-9999", message)

    def test_out_of_order_event_fails_without_regressing_latest(self):
        late = copy.deepcopy(self.events[0])
        late["eventId"] = "evt-old"
        late["sourceTimestamp"] = 1795680002500
        late["sequence"] = 3
        self.events.append(late)

        report = validate_events.validate_events(self.mapping, self.events)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("OUT_OF_ORDER_EVENT", self.codes(report))
        self.assertEqual(report["summary"]["out_of_order_events"], 1)
        person = next(
            item for item in report["latest_by_entity"] if item["entityId"] == "PERSON-001"
        )
        self.assertEqual(person["sourceTimestamp"], 1795680003000)
        self.assertEqual(person["sequence"], 2)

    def test_position_quality_and_coordinate_system_are_required(self):
        self.events[0]["payload"]["positionQuality"] = "GOOD"
        del self.events[0]["payload"]["position"]["coordinateSystemId"]
        report = validate_events.validate_events(self.mapping, self.events)

        codes = self.codes(report)
        self.assertIn("INVALID_POSITION_QUALITY", codes)
        self.assertIn("MISSING_COORDINATE_SYSTEM", codes)

    def test_mapping_entity_mismatch_is_detected(self):
        self.events[0]["entityId"] = "PERSON-002"
        report = validate_events.validate_events(self.mapping, self.events)

        codes = self.codes(report)
        self.assertIn("DEVICE_ENTITY_MISMATCH", codes)
        self.assertEqual(report["status"], "FAIL")

    def test_outputs_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = validate_events.main(
                    [
                        str(FIXTURES / "device_mapping.json"),
                        str(FIXTURES / "events.jsonl"),
                        "--out-dir",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("PASS", stdout.getvalue())

            report_path = Path(tmp) / "integration_report.json"
            markdown_path = Path(tmp) / "integration_report.md"
            issues_path = Path(tmp) / "issues.csv"
            self.assertTrue(report_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue(issues_path.exists())

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["events_total"], 4)
            self.assertIn("# IoT Integration Validation Report", markdown_path.read_text(encoding="utf-8"))

            with issues_path.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows, [])

            bad_events = copy.deepcopy(self.events)
            bad_events[0]["payload"]["sourceDeviceId"] = "TL-9999"
            bad_report = validate_events.validate_events(self.mapping, bad_events)
            bad_paths = validate_events.write_outputs(bad_report, Path(tmp) / "bad")
            with open(bad_paths["issues_csv"], encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertTrue(any(row["code"] == "UNKNOWN_DEVICE" for row in rows))


if __name__ == "__main__":
    unittest.main()
