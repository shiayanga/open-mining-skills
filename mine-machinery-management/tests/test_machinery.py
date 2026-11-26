#!/usr/bin/env python3
"""Tests for the mine-machinery-management processor."""

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

import machinery  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class MachineryTests(unittest.TestCase):
    def setUp(self):
        self.registry = copy.deepcopy(machinery.read_json(FIXTURES / "registry.json"))
        self.state_map = copy.deepcopy(machinery.read_json(FIXTURES / "state_map.json"))
        self.events = copy.deepcopy(machinery.read_jsonl(FIXTURES / "telemetry.jsonl"))

    def process(self, events=None):
        return machinery.process_machinery(
            self.registry,
            self.state_map,
            self.events if events is None else events,
        )

    def codes(self, result):
        return {issue["code"] for issue in result["report"]["issues"]}

    def latest_machine(self, result, machinery_id):
        return next(
            item
            for item in result["latest_state"]["machinery"]
            if item["machineryId"] == machinery_id
        )

    def test_valid_processing_and_state_mapping(self):
        result = self.process()
        report = result["report"]
        summary = report["summary"]

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(summary["registry_machinery"], 2)
        self.assertEqual(summary["telemetry_events"], 3)
        self.assertEqual(summary["accepted_events"], 3)
        self.assertEqual(summary["tracks_written"], 2)
        self.assertEqual(summary["machines_updated"], 2)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 0)
        self.assertEqual(summary["state_counts"], {"HAULING": 1, "IDLE": 1, "WORKING": 1})
        self.assertEqual(
            summary["animation_counts"],
            {"Excavator_Idle": 1, "Excavator_Work": 1, "Truck_Haul": 1},
        )

        excavator = self.latest_machine(result, "EXC-001")
        self.assertEqual(excavator["state"], "IDLE")
        self.assertEqual(excavator["animation"], "Excavator_Idle")
        self.assertEqual(excavator["animationConfig"]["loop"], True)
        self.assertEqual(excavator["position"]["x"], 100.0)
        self.assertEqual(excavator["speed"], 5.0)
        self.assertEqual(excavator["eventCount"], 2)

        truck = self.latest_machine(result, "TRUCK-001")
        self.assertEqual(truck["state"], "HAULING")
        self.assertEqual(truck["animation"], "Truck_Haul")
        self.assertEqual(truck["position"]["x"], 400.0)

    def test_out_of_order_telemetry_is_ignored(self):
        old = copy.deepcopy(self.events[0])
        old["eventId"] = "mach-old"
        old["sourceTimestamp"] = 1795680001500
        old["sequence"] = 9
        old["payload"]["position"]["x"] = 999.0
        old["payload"]["state"] = "WORKING"
        result = self.process(self.events + [old])

        self.assertIn("OUT_OF_ORDER_IGNORED", self.codes(result))
        self.assertEqual(result["report"]["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["report"]["summary"]["out_of_order_ignored"], 1)
        self.assertEqual(result["report"]["summary"]["accepted_events"], 3)
        self.assertEqual(result["report"]["summary"]["tracks_written"], 2)
        excavator = self.latest_machine(result, "EXC-001")
        self.assertEqual(excavator["position"]["x"], 100.0)
        self.assertEqual(excavator["state"], "IDLE")
        self.assertEqual(excavator["animation"], "Excavator_Idle")

    def test_unknown_machinery_is_flagged(self):
        unknown = {
            "eventId": "mach-unknown",
            "eventType": "MACHINERY_STATUS_UPDATE",
            "machineryId": "EXC-999",
            "mineId": "MINE-001",
            "sourceTimestamp": 1795680003000,
            "sequence": 1,
            "payload": {"state": "WORKING"},
        }
        result = self.process(self.events + [unknown])

        self.assertEqual(result["report"]["status"], "FAIL")
        self.assertIn("UNKNOWN_MACHINERY", self.codes(result))
        self.assertEqual(result["report"]["summary"]["unknown_machinery"], 1)
        message = next(
            issue["message"]
            for issue in result["report"]["issues"]
            if issue["code"] == "UNKNOWN_MACHINERY"
        )
        self.assertIn("EXC-999", message)

    def test_orientation_ranges_are_validated(self):
        self.events[0]["payload"]["orientation"] = {
            "heading": 450.0,
            "pitch": -91.0,
            "roll": 181.0,
        }
        result = self.process()

        self.assertEqual(result["report"]["status"], "FAIL")
        self.assertIn("ORIENTATION_OUT_OF_RANGE", self.codes(result))
        out_of_range = [
            issue for issue in result["report"]["issues"]
            if issue["code"] == "ORIENTATION_OUT_OF_RANGE"
        ]
        self.assertEqual(
            {issue["field"] for issue in out_of_range},
            {"orientation.heading", "orientation.pitch", "orientation.roll"},
        )

    def test_unknown_state_is_kept_without_animation(self):
        self.events[1]["payload"]["state"] = "FLYING"
        result = self.process()

        self.assertEqual(result["report"]["status"], "PASS_WITH_WARNINGS")
        self.assertIn("UNKNOWN_STATE", self.codes(result))
        excavator = self.latest_machine(result, "EXC-001")
        self.assertEqual(excavator["state"], "FLYING")
        self.assertIsNone(excavator["animation"])

    def test_outputs_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = machinery.main(
                    [
                        str(FIXTURES / "registry.json"),
                        str(FIXTURES / "telemetry.jsonl"),
                        str(FIXTURES / "state_map.json"),
                        "--out-dir",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("PASS", stdout.getvalue())

            latest_path = Path(tmp) / "latest_state.json"
            tracks_path = Path(tmp) / "tracks.csv"
            report_path = Path(tmp) / "machinery_report.json"
            markdown_path = Path(tmp) / "machinery_report.md"
            for path in (latest_path, tracks_path, report_path, markdown_path):
                self.assertTrue(path.exists(), path)

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest["count"], 2)
            self.assertEqual(
                {item["machineryId"] for item in latest["machinery"]},
                {"EXC-001", "TRUCK-001"},
            )

            with tracks_path.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["machinery_id"], "EXC-001")
            self.assertEqual(rows[0]["animation"], "Excavator_Work")

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["machines_updated"], 2)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Machinery Management Report", markdown)


if __name__ == "__main__":
    unittest.main()
