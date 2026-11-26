#!/usr/bin/env python3
"""Tests for the mine-project-orchestrator planner."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import orchestrate  # noqa: E402

DEFAULT_MANIFEST = SKILL_DIR / "references" / "skills_manifest.json"

EXPECTED_SKILLS = {
    "mine-data-inspection",
    "mine-cad-parser",
    "mine-coordinate-registration",
    "mine-terrain-modeling",
    "mine-point-cloud",
    "mine-3d-modeling",
    "mine-geological-modeling",
    "mine-3d-tiles",
    "mine-3d-entity-binding",
    "mine-iot-integration",
    "mine-personnel-tracking",
    "mine-safety-monitoring",
    "mine-machinery-management",
    "mine-cesium-visualization",
    "mine-scene-interaction",
    "mine-model-quality-check",
    "mine-project-orchestrator",
}


def load_default_manifest() -> dict:
    return orchestrate.load_manifest(DEFAULT_MANIFEST)


def custom_manifest(consumer_required: list[str]) -> dict:
    return orchestrate.normalize_manifest(
        {
            "manifestVersion": "test",
            "skills": [
                {
                    "name": "mine-source",
                    "stage": "intake",
                    "keywords": ["source"],
                    "inputs": ["raw input"],
                    "outputs": ["source.json"],
                    "acceptance": ["Source step completed."],
                    "consumes": [],
                    "produces": ["source_report"],
                    "requires": [],
                },
                {
                    "name": "mine-consumer",
                    "stage": "modeling",
                    "keywords": ["consumer"],
                    "inputs": ["source.json"],
                    "outputs": ["model.glb"],
                    "acceptance": ["Consumer step completed."],
                    "consumes": ["source_report"],
                    "produces": ["glb_model"],
                    "requires": consumer_required,
                },
            ],
        }
    )


def simple_manifest(consumer_inputs: list[str]) -> dict:
    """A manifest that declares only name/stage/keywords/inputs/outputs."""
    return orchestrate.normalize_manifest(
        {
            "manifestVersion": "test",
            "skills": [
                {
                    "name": "mine-source",
                    "stage": "intake",
                    "keywords": ["source"],
                    "inputs": ["raw input"],
                    "outputs": ["source.json"],
                },
                {
                    "name": "mine-consumer",
                    "stage": "modeling",
                    "keywords": ["consumer"],
                    "inputs": consumer_inputs,
                    "outputs": ["model.glb"],
                },
            ],
        }
    )


class ManifestTests(unittest.TestCase):
    def test_default_manifest_covers_17_skills(self):
        manifest = load_default_manifest()

        names = {skill["name"] for skill in manifest["skills"]}
        self.assertEqual(len(manifest["skills"]), 17)
        self.assertEqual(names, EXPECTED_SKILLS)
        self.assertFalse(manifest["by_name"]["mine-project-orchestrator"]["selectable"])

    def test_manifest_validation_rejects_missing_outputs(self):
        with self.assertRaises(orchestrate.ManifestError):
            orchestrate.normalize_manifest(
                {
                    "skills": [
                        {
                            "name": "mine-broken",
                            "stage": "intake",
                            "keywords": ["broken"],
                            "inputs": ["input"],
                        }
                    ]
                }
            )

    def test_manifest_validation_rejects_duplicate_names(self):
        skill = {
            "name": "mine-duplicate",
            "stage": "intake",
            "keywords": ["duplicate"],
            "inputs": ["input"],
            "outputs": ["output"],
        }
        with self.assertRaises(orchestrate.ManifestError):
            orchestrate.normalize_manifest({"skills": [skill, dict(skill)]})

    def test_manifest_validation_rejects_unknown_dependency(self):
        with self.assertRaises(orchestrate.ManifestError):
            orchestrate.normalize_manifest(
                {
                    "skills": [
                        {
                            "name": "mine-dependent",
                            "stage": "modeling",
                            "keywords": ["dependent"],
                            "inputs": ["input"],
                            "outputs": ["output"],
                            "dependsOn": ["mine-does-not-exist"],
                        }
                    ]
                }
            )


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_default_manifest()

    def test_dxf_terrain_request_selects_expected_chain(self):
        plan = orchestrate.build_task_plan(
            "解析这个 DXF 文件并重建地形", self.manifest
        )

        self.assertEqual(plan["status"], "READY")
        self.assertEqual(
            plan["selectedSkills"],
            [
                "mine-data-inspection",
                "mine-cad-parser",
                "mine-terrain-modeling",
            ],
        )
        self.assertEqual([step["step"] for step in plan["steps"]], [1, 2, 3])
        self.assertEqual(plan["handoffValidation"]["status"], "OK")
        self.assertEqual(plan["errors"], [])
        self.assertIn(
            "inspection_report",
            [artifact for link in plan["handoffValidation"]["links"] for artifact in link["artifacts"]],
        )
        for step in plan["steps"]:
            self.assertTrue(step["owner"])
            self.assertTrue(step["inputs"])
            self.assertTrue(step["outputs"])
            self.assertTrue(step["acceptanceChecks"])

    def test_digital_twin_request_selects_business_skills(self):
        plan = orchestrate.build_task_plan(
            "建设矿山数字孪生：人员定位、安全监测、机械设备管理、三维绑定、点击交互",
            self.manifest,
        )

        selected = plan["selectedSkills"]
        self.assertEqual(plan["status"], "READY")
        self.assertEqual(plan["handoffValidation"]["status"], "OK")
        for expected in (
            "mine-3d-entity-binding",
            "mine-personnel-tracking",
            "mine-safety-monitoring",
            "mine-machinery-management",
            "mine-scene-interaction",
        ):
            self.assertIn(expected, selected)
        self.assertEqual(selected[0], "mine-3d-entity-binding")
        self.assertLess(selected.index("mine-3d-entity-binding"), selected.index("mine-personnel-tracking"))
        self.assertEqual(plan["steps"][0]["owner"], "mine-3d-entity-binding")

    def test_unknown_request_fails(self):
        plan = orchestrate.build_task_plan("请写一首关于春天的诗", self.manifest)

        self.assertEqual(plan["status"], "FAILED")
        self.assertEqual(plan["selectedSkills"], [])
        self.assertEqual(plan["steps"], [])
        self.assertIn("NO_SKILL_MATCH", {error["code"] for error in plan["errors"]})
        self.assertEqual(plan["handoffValidation"]["status"], "EMPTY")

    def test_allow_empty_produces_empty_plan(self):
        plan = orchestrate.build_task_plan(
            "请写一首关于春天的诗", self.manifest, allow_empty=True
        )

        self.assertEqual(plan["status"], "EMPTY")
        self.assertEqual(plan["errors"], [])
        self.assertTrue(plan["warnings"])
        self.assertEqual(plan["selectedSkills"], [])

    def test_short_ascii_keywords_do_not_match_inside_words(self):
        plan = orchestrate.build_task_plan("this is testing the tool", self.manifest)

        self.assertEqual(plan["status"], "FAILED")
        self.assertEqual(plan["selectedSkills"], [])

    def test_broken_handoff_is_detected(self):
        manifest = custom_manifest(["terrain_mesh"])
        plan = orchestrate.build_task_plan(
            "source then consumer", manifest
        )

        self.assertEqual(plan["status"], "FAILED")
        self.assertEqual(plan["handoffValidation"]["status"], "BROKEN")
        self.assertIn(
            "BROKEN_HANDOFF",
            {error["code"] for error in plan["handoffValidation"]["errors"]},
        )
        self.assertIn("BROKEN_HANDOFF", {error["code"] for error in plan["errors"]})

    def test_valid_handoff_chain(self):
        manifest = custom_manifest(["source_report"])
        plan = orchestrate.build_task_plan(
            "source then consumer", manifest
        )

        self.assertEqual(plan["status"], "READY")
        self.assertEqual(plan["handoffValidation"]["status"], "OK")
        self.assertEqual(len(plan["handoffValidation"]["links"]), 1)
        link = plan["handoffValidation"]["links"][0]
        self.assertEqual(link["from"], "mine-source")
        self.assertEqual(link["to"], "mine-consumer")
        self.assertIn("source_report", link["artifacts"])

    def test_simple_manifest_handoff_uses_inputs_and_outputs(self):
        manifest = simple_manifest(["source.json"])
        plan = orchestrate.build_task_plan("source then consumer", manifest)

        self.assertEqual(plan["status"], "READY")
        self.assertEqual(plan["handoffValidation"]["status"], "OK")
        self.assertEqual(plan["steps"][1]["artifactContract"], "inputs_outputs")
        self.assertEqual(plan["steps"][1]["requiredArtifacts"], ["source.json"])
        self.assertEqual(plan["handoffValidation"]["links"][0]["artifacts"], ["source.json"])

    def test_simple_manifest_broken_chain_is_detected(self):
        manifest = simple_manifest(["terrain_mesh"])
        plan = orchestrate.build_task_plan("source then consumer", manifest)

        self.assertEqual(plan["status"], "FAILED")
        self.assertEqual(plan["handoffValidation"]["status"], "BROKEN")
        self.assertIn(
            "BROKEN_HANDOFF",
            {error["code"] for error in plan["handoffValidation"]["errors"]},
        )

    def test_empty_request_is_rejected(self):
        with self.assertRaises(orchestrate.RequestError):
            orchestrate.build_task_plan("   ", self.manifest)


class OutputTests(unittest.TestCase):
    def test_markdown_renderer(self):
        manifest = load_default_manifest()
        plan = orchestrate.build_task_plan("解析 DXF 并重建地形", manifest)
        markdown = orchestrate.render_markdown(plan)

        self.assertIn("# Mine Project Orchestration Report", markdown)
        self.assertIn("mine-terrain-modeling", markdown)
        self.assertIn("Handoff Validation", markdown)

    def test_write_outputs(self):
        manifest = load_default_manifest()
        plan = orchestrate.build_task_plan("解析 DXF 并重建地形", manifest)
        with tempfile.TemporaryDirectory() as tmp:
            paths = orchestrate.write_outputs(plan, tmp)
            written = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

        self.assertEqual(written["status"], "READY")
        self.assertEqual(written["selectedSkills"][0], "mine-data-inspection")
        self.assertIn("# Mine Project Orchestration Report", markdown)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = orchestrate.main(
                [
                    "解析 DXF 并重建地形",
                    "--manifest",
                    str(DEFAULT_MANIFEST),
                    "--out-dir",
                    tmp,
                ]
            )
            self.assertEqual(ok, 0)
            plan = json.loads((Path(tmp) / "task_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["status"], "READY")

            failed = orchestrate.main(
                [
                    "请写一首关于春天的诗",
                    "--manifest",
                    str(DEFAULT_MANIFEST),
                    "--out-dir",
                    tmp,
                ]
            )
            self.assertEqual(failed, 1)
            failed_plan = json.loads(
                (Path(tmp) / "task_plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failed_plan["status"], "FAILED")

            allowed = orchestrate.main(
                [
                    "请写一首关于春天的诗",
                    "--manifest",
                    str(DEFAULT_MANIFEST),
                    "--out-dir",
                    tmp,
                    "--allow-empty",
                ]
            )
            self.assertEqual(allowed, 0)
            empty_plan = json.loads(
                (Path(tmp) / "task_plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(empty_plan["status"], "EMPTY")

    def test_cli_rejects_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "bad_manifest.json"
            manifest_path.write_text(json.dumps({}), encoding="utf-8")
            result = orchestrate.main(
                [
                    "解析 DXF",
                    "--manifest",
                    str(manifest_path),
                    "--out-dir",
                    str(Path(tmp) / "out"),
                ]
            )
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
