#!/usr/bin/env python3
"""Tests for the mine-personnel-tracking processor."""

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

import tracking  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.events = copy.deepcopy(tracking.read_jsonl(FIXTURES / "positions.jsonl"))
        self.geofences = copy.deepcopy(tracking.read_json(FIXTURES / "geofences.json"))

    def codes(self, result):
        return {issue["code"] for issue in result["report"]["issues"]}

    def test_valid_processing(self):
        result = tracking.process_tracking(self.events, self.geofences)
        report = result["report"]
        summary = report["summary"]

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(summary["events_total"], 5)
        self.assertEqual(summary["positions_accepted"], 5)
        self.assertEqual(summary["tracks_written"], 5)
        self.assertEqual(summary["persons_tracked"], 2)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 0)
        self.assertEqual(summary["geofence_enters"], 2)
        self.assertEqual(summary["geofence_exits"], 1)
        self.assertEqual(summary["positions_inside_any"], 1)
        self.assertEqual(summary["positions_outside_all"], 1)
        self.assertEqual(summary["quality_counts"], {"VALID": 5})

        latest = {
            item["entityId"]: item for item in result["latest_positions"]["positions"]
        }
        self.assertEqual(result["latest_positions"]["count"], 2)
        self.assertEqual(latest["PERSON-001"]["position"]["x"], 25.0)
        self.assertEqual(latest["PERSON-001"]["insideGeofences"], [])
        self.assertEqual(latest["PERSON-002"]["insideGeofences"], ["GF-001"])

        area = report["area_counts"][0]
        self.assertEqual(area["geofenceId"], "GF-001")
        self.assertEqual(area["count"], 1)
        self.assertEqual(area["entityIds"], ["PERSON-002"])

    def test_out_of_order_event_is_ignored(self):
        old = copy.deepcopy(self.events[0])
        old["eventId"] = "evt-old"
        old["sourceTimestamp"] = 1795680001500
        old["sequence"] = 9
        old["payload"]["position"]["x"] = 15.0
        old["payload"]["position"]["y"] = 15.0
        self.events.append(old)

        result = tracking.process_tracking(self.events, self.geofences)
        report = result["report"]

        self.assertIn("OUT_OF_ORDER_IGNORED", self.codes(result))
        self.assertEqual(report["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(report["summary"]["out_of_order_ignored"], 1)
        self.assertEqual(report["summary"]["positions_accepted"], 5)
        self.assertEqual(report["summary"]["tracks_written"], 5)
        latest = {
            item["entityId"]: item for item in result["latest_positions"]["positions"]
        }
        self.assertEqual(latest["PERSON-001"]["position"]["x"], 25.0)
        self.assertEqual(latest["PERSON-001"]["insideGeofences"], [])
        self.assertEqual(report["summary"]["geofence_events"], 3)

    def test_geofence_entry_and_exit_detected(self):
        result = tracking.process_tracking(self.events, self.geofences)
        events = [
            (item["eventType"], item["entityId"], item["geofenceId"])
            for item in result["geofence_events"]
        ]
        self.assertEqual(
            events,
            [
                ("PERSONNEL_ENTER_AREA", "PERSON-001", "GF-001"),
                ("PERSONNEL_LEAVE_AREA", "PERSON-001", "GF-001"),
                ("PERSONNEL_ENTER_AREA", "PERSON-002", "GF-001"),
            ],
        )

    def test_invalid_quality_is_not_counted_as_presence(self):
        self.events[4]["payload"].pop("positionQuality")
        result = tracking.process_tracking(self.events, self.geofences)

        self.assertIn("MISSING_POSITION_QUALITY", self.codes(result))
        self.assertEqual(result["report"]["summary"]["quality_counts"]["INVALID"], 1)
        latest = {
            item["entityId"]: item for item in result["latest_positions"]["positions"]
        }
        self.assertEqual(latest["PERSON-002"]["positionQuality"], "INVALID")
        self.assertEqual(result["report"]["area_counts"][0]["count"], 0)

    def test_outputs_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = tracking.main(
                    [
                        str(FIXTURES / "positions.jsonl"),
                        str(FIXTURES / "geofences.json"),
                        "--out-dir",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("PASS", stdout.getvalue())

            paths = {
                name: Path(tmp) / name
                for name in (
                    "latest_positions.json",
                    "tracks.csv",
                    "geofence_events.jsonl",
                    "tracking_report.json",
                    "tracking_report.md",
                )
            }
            for path in paths.values():
                self.assertTrue(path.exists(), path)

            latest = json.loads(paths["latest_positions.json"].read_text(encoding="utf-8"))
            self.assertEqual(latest["count"], 2)

            with paths["tracks.csv"].open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 5)
            self.assertIn("inside_geofences", rows[0])
            self.assertEqual(rows[0]["entity_id"], "PERSON-001")

            geofence_lines = paths["geofence_events.jsonl"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(geofence_lines), 3)
            self.assertEqual(
                json.loads(geofence_lines[0])["eventType"], "PERSONNEL_ENTER_AREA"
            )

            report = json.loads(paths["tracking_report.json"].read_text(encoding="utf-8"))
            self.assertEqual(report["area_counts"][0]["count"], 1)
            markdown = paths["tracking_report.md"].read_text(encoding="utf-8")
            self.assertIn("# Personnel Tracking Report", markdown)


if __name__ == "__main__":
    unittest.main()
