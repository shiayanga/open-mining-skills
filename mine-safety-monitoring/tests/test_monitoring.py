#!/usr/bin/env python3
"""Tests for the mine-safety-monitoring processor."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import monitoring  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.metrics = copy.deepcopy(monitoring.read_json(FIXTURES / "metrics.json"))
        self.thresholds = copy.deepcopy(monitoring.read_json(FIXTURES / "thresholds.json"))
        self.events = copy.deepcopy(monitoring.read_jsonl(FIXTURES / "events.jsonl"))

    def process(self, events=None, stale_after_ms=300000):
        return monitoring.process_monitoring(
            self.metrics,
            self.thresholds,
            self.events if events is None else events,
            stale_after_ms=stale_after_ms,
        )

    def codes(self, result):
        return {issue["code"] for issue in result["report"]["issues"]}

    def latest_device(self, result, entity_id):
        return next(
            device
            for device in result["latest_values"]["devices"]
            if device["entityId"] == entity_id
        )

    def test_valid_processing(self):
        result = self.process()
        report = result["report"]
        summary = report["summary"]

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(summary["events_total"], 5)
        self.assertEqual(summary["events_accepted"], 5)
        self.assertEqual(summary["devices_monitored"], 2)
        self.assertEqual(summary["online_devices"], 2)
        self.assertEqual(summary["offline_devices"], 0)
        self.assertEqual(summary["stale_devices"], 0)
        self.assertEqual(summary["metric_updates"], 5)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 0)
        self.assertEqual(summary["alarms"]["created"], 1)
        self.assertEqual(summary["alarms"]["cleared"], 1)
        self.assertEqual(summary["alarms"]["active"], 0)
        self.assertEqual(summary["threshold_version"], "2026.11-v1")

        ch4 = self.latest_device(result, "MON-001")
        self.assertEqual(ch4["status"], "ONLINE")
        self.assertEqual(ch4["metrics"][0]["value"], 0.2)
        self.assertEqual(ch4["metrics"][0]["status"], "NORMAL")
        self.assertEqual(ch4["alarmStatus"], "NORMAL")
        temp = self.latest_device(result, "MON-002")
        self.assertEqual(temp["metrics"][0]["value"], 30.0)

        alarm_actions = [
            (alarm["payload"]["action"], alarm["payload"]["status"])
            for alarm in result["alarms"]
        ]
        self.assertEqual(alarm_actions, [("CREATED", "ACTIVE"), ("CLEARED", "CLEARED")])

    def test_threshold_crossing_creates_alarm(self):
        result = self.process(self.events[:2])
        report = result["report"]

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["alarms"]["created"], 1)
        self.assertEqual(report["summary"]["alarms"]["active"], 1)
        self.assertEqual(len(result["generated_alarms"]), 1)
        alarm = result["generated_alarms"][0]
        self.assertEqual(alarm["eventType"], "MONITOR_ALARM")
        self.assertEqual(alarm["payload"]["alarmType"], "THRESHOLD")
        self.assertEqual(alarm["payload"]["alarmLevel"], "WARNING")
        self.assertEqual(alarm["payload"]["metricCode"], "CH4")
        self.assertEqual(alarm["payload"]["threshold"], 0.8)
        self.assertEqual(alarm["payload"]["currentValue"], 0.9)
        self.assertEqual(alarm["payload"]["status"], "ACTIVE")

        ch4 = self.latest_device(result, "MON-001")
        self.assertEqual(ch4["metrics"][0]["status"], "WARNING")
        self.assertEqual(ch4["alarmStatus"], "WARNING")
        self.assertEqual(len(ch4["activeAlarms"]), 1)

    def test_repeated_event_does_not_duplicate_alarm(self):
        result = self.process(self.events[:3])

        self.assertEqual(result["report"]["summary"]["alarms"]["created"], 1)
        self.assertEqual(len(result["generated_alarms"]), 1)
        self.assertEqual(len(result["report"]["active_alarms"]), 1)
        active = result["report"]["active_alarms"][0]
        self.assertEqual(active["eventCount"], 2)
        self.assertEqual(active["lastValue"], 0.95)

    def test_value_back_to_normal_clears_alarm(self):
        result = self.process()
        alarms = result["generated_alarms"]

        self.assertEqual(len(alarms), 2)
        self.assertEqual(alarms[0]["payload"]["action"], "CREATED")
        self.assertEqual(alarms[1]["payload"]["action"], "CLEARED")
        self.assertEqual(alarms[1]["payload"]["status"], "CLEARED")
        self.assertEqual(result["report"]["summary"]["alarms"]["active"], 0)
        ch4 = self.latest_device(result, "MON-001")
        self.assertEqual(ch4["metrics"][0]["status"], "NORMAL")
        self.assertEqual(ch4["activeAlarms"], [])

    def test_stale_device_is_flagged(self):
        result = self.process(stale_after_ms=500)
        report = result["report"]

        self.assertEqual(report["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(report["summary"]["stale_devices"], 1)
        self.assertIn("DEVICE_STALE", self.codes(result))
        temp = self.latest_device(result, "MON-002")
        ch4 = self.latest_device(result, "MON-001")
        self.assertEqual(temp["status"], "STALE")
        self.assertEqual(ch4["status"], "ONLINE")
        self.assertEqual(result["latest_values"]["staleAfterMs"], 500)

    def test_out_of_order_value_is_ignored(self):
        old = copy.deepcopy(self.events[0])
        old["eventId"] = "evt-old"
        old["sourceTimestamp"] = 1795680000500
        old["sequence"] = 9
        old["payload"]["metrics"][0]["value"] = 4.0
        result = self.process(self.events + [old])

        self.assertIn("OUT_OF_ORDER_IGNORED", self.codes(result))
        self.assertEqual(result["report"]["summary"]["out_of_order_ignored"], 1)
        ch4 = self.latest_device(result, "MON-001")
        self.assertEqual(ch4["metrics"][0]["value"], 0.2)

    def test_outputs_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = monitoring.main(
                    [
                        str(FIXTURES / "metrics.json"),
                        str(FIXTURES / "thresholds.json"),
                        str(FIXTURES / "events.jsonl"),
                        "--out-dir",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("PASS", stdout.getvalue())

            latest_path = Path(tmp) / "latest_values.json"
            alarms_path = Path(tmp) / "alarms.jsonl"
            report_path = Path(tmp) / "monitoring_report.json"
            markdown_path = Path(tmp) / "monitoring_report.md"
            for path in (latest_path, alarms_path, report_path, markdown_path):
                self.assertTrue(path.exists(), path)

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(latest["devices"]), 2)
            alarm_lines = alarms_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(alarm_lines), 2)
            self.assertEqual(
                json.loads(alarm_lines[0])["payload"]["action"], "CREATED"
            )

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["alarms"]["cleared"], 1)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Safety Monitoring Report", markdown)


if __name__ == "__main__":
    unittest.main()
