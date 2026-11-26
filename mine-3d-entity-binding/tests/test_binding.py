#!/usr/bin/env python3
"""Tests for the mine-3d-entity-binding validator."""

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

import binding  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.entities = copy.deepcopy(
            binding.load_collection(FIXTURES / "entities.json", ("entities",), "Entity")
        )
        self.objects = copy.deepcopy(
            binding.load_collection(
                FIXTURES / "scene_objects.json", ("sceneObjects",), "Scene object"
            )
        )
        self.models = copy.deepcopy(
            binding.load_collection(FIXTURES / "models.json", ("models",), "Model")
        )
        self.bindings = copy.deepcopy(
            binding.load_collection(FIXTURES / "bindings.json", ("bindings",), "Binding")
        )

    def validate(self, query=None):
        return binding.validate_binding_set(
            self.entities, self.objects, self.models, self.bindings, query_entity_id=query
        )

    def codes(self, report):
        return {issue["code"] for issue in report["issues"]}

    def test_valid_set_and_entity_query(self):
        report = self.validate(query="PERSON-001")

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["entities"], 3)
        self.assertEqual(report["summary"]["scene_objects"], 4)
        self.assertEqual(report["summary"]["models"], 4)
        self.assertEqual(report["summary"]["bindings"], 4)
        self.assertEqual(report["summary"]["primary_bindings"], 3)

        query = report["query"]
        self.assertEqual(query["entity"]["entityId"], "PERSON-001")
        self.assertEqual(len(query["objects"]), 2)
        self.assertEqual(len(query["bindings"]), 2)
        self.assertEqual(query["primaryBindingId"], "BIND-001")
        self.assertEqual(
            {item["objectId"] for item in query["objects"]},
            {"OBJ-PERSON-001", "OBJ-PERSON-MARKER-001"},
        )
        self.assertEqual(
            {item["modelId"] for item in query["bindings"]},
            {"MODEL-WORKER", "MODEL-MARKER"},
        )

    def test_missing_entity_fails(self):
        self.bindings.append(
            {
                "bindingId": "BIND-BAD-ENTITY",
                "entityId": "PERSON-999",
                "objectId": "OBJ-PERSON-001",
                "bindingType": "ENTITY_MODEL",
                "modelId": "MODEL-WORKER",
                "isPrimary": False,
            }
        )
        report = self.validate()

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("MISSING_ENTITY", self.codes(report))
        message = next(
            issue["message"] for issue in report["issues"] if issue["code"] == "MISSING_ENTITY"
        )
        self.assertIn("PERSON-999", message)

    def test_conflicting_primary_fails(self):
        self.bindings[1]["isPrimary"] = True
        report = self.validate()

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("CONFLICTING_PRIMARY", self.codes(report))
        issue = next(
            issue for issue in report["issues"] if issue["code"] == "CONFLICTING_PRIMARY"
        )
        self.assertEqual(issue["entityId"], "PERSON-001")
        self.assertEqual(set(issue["bindingIds"]), {"BIND-001", "BIND-002"})

    def test_cross_mine_binding_fails(self):
        self.objects[0]["mineId"] = "MINE-002"
        report = self.validate()

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("CROSS_MINE", self.codes(report))
        messages = [issue["message"] for issue in report["issues"] if issue["code"] == "CROSS_MINE"]
        self.assertTrue(any("MINE-001" in message and "MINE-002" in message for message in messages))

    def test_duplicate_entity_object_pair_fails(self):
        self.bindings.append(
            {
                "bindingId": "BIND-DUPLICATE",
                "entityId": "PERSON-001",
                "objectId": "OBJ-PERSON-001",
                "bindingType": "ENTITY_MARKER",
                "isPrimary": False,
            }
        )
        report = self.validate()

        self.assertIn("DUPLICATE_ENTITY_OBJECT", self.codes(report))
        self.assertEqual(report["status"], "FAIL")

    def test_empty_model_node_and_unknown_node_fail(self):
        self.bindings[0]["modelNodeId"] = ""
        self.bindings[2]["modelNodeId"] = "Missing_Node"
        report = self.validate()

        codes = self.codes(report)
        self.assertIn("EMPTY_MODEL_NODE_ID", codes)
        self.assertIn("UNKNOWN_MODEL_NODE", codes)

    def test_output_files_and_cli_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = binding.main(
                    [
                        "--entities",
                        str(FIXTURES / "entities.json"),
                        "--objects",
                        str(FIXTURES / "scene_objects.json"),
                        "--models",
                        str(FIXTURES / "models.json"),
                        "--bindings",
                        str(FIXTURES / "bindings.json"),
                        "--entity",
                        "MACHINERY-001",
                        "--out-dir",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            query = json.loads(stdout.getvalue())
            self.assertEqual(query["entityId"], "MACHINERY-001")
            self.assertEqual(query["primaryBindingId"], "BIND-003")

            json_path = Path(tmp) / "binding_report.json"
            markdown_path = Path(tmp) / "binding_report.md"
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())

            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["bindings"], 4)
            self.assertEqual(report["query"]["entityId"], "MACHINERY-001")
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# 3D Entity Binding Report", markdown)
            self.assertIn("## Entity Query", markdown)


if __name__ == "__main__":
    unittest.main()
