#!/usr/bin/env python3
"""Plan a mine 3D / digital twin request across the available skills.

The orchestrator reads a skills manifest, matches request keywords, adds
required upstream producers, orders the steps topologically and validates the
artifact handoffs. It produces a plan only; it never executes another skill.
"""

from __future__ import annotations

import argparse
import heapq
import re
import sys
from pathlib import Path

import common

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "references" / "skills_manifest.json"
)

# Default stage order. Stages not in this list are ordered after known stages
# and then by manifest position.
STAGE_ORDER = [
    "intake",
    "parse",
    "coordinate",
    "modeling",
    "tiling",
    "integration",
    "digital-twin",
    "visualization",
    "interaction",
    "quality",
    "orchestration",
]
STAGE_RANK = {stage: index for index, stage in enumerate(STAGE_ORDER)}

LIMITATIONS = [
    "Keyword matching is literal and case-insensitive; it does not understand "
    "negation or intent beyond the manifest keywords.",
    "The orchestrator produces a plan and does not execute any skill.",
    "Optional inputs are not fetched or checked; only declared required "
    "artifact handoffs are validated.",
    "Custom stages are accepted but ordered after the documented default stages.",
]


class ManifestError(ValueError):
    """Raised when skills_manifest.json is structurally invalid."""


class RequestError(ValueError):
    """Raised when the user request is empty."""


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _artifact_key(value: str) -> str:
    """Normalise a human-readable input/output name for fallback matching."""
    return " ".join(value.strip().lower().replace("\\", "/").split())


def _string_list(
    value: object,
    path: str,
    *,
    required: bool = True,
    allow_empty: bool = True,
) -> list[str]:
    if value is None:
        if required:
            raise ManifestError(f"{path} is required")
        return []
    if not isinstance(value, list):
        raise ManifestError(f"{path} must be an array")
    if not value and not allow_empty:
        raise ManifestError(f"{path} must not be empty")
    result: list[str] = []
    for index, item in enumerate(value):
        if not _is_nonempty_str(item):
            raise ManifestError(f"{path}[{index}] must be a non-empty string")
        result.append(item.strip())
    return result


def normalize_manifest(data: object, source_path: str | None = None) -> dict:
    """Validate and normalise a skills manifest."""
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be a JSON object")
    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise ManifestError("skills must be a non-empty array")

    skills: list[dict] = []
    by_name: dict[str, dict] = {}
    for index, raw in enumerate(raw_skills):
        path = f"skills[{index}]"
        if not isinstance(raw, dict):
            raise ManifestError(f"{path} must be an object")
        name_value = raw.get("name")
        if not _is_nonempty_str(name_value):
            raise ManifestError(f"{path}.name must be a non-empty string")
        name = name_value.strip()
        if name in by_name:
            raise ManifestError(f"duplicate skill name '{name}'")
        stage_value = raw.get("stage")
        if not _is_nonempty_str(stage_value):
            raise ManifestError(f"{path}.stage must be a non-empty string")
        selectable = raw.get("selectable", True)
        if not isinstance(selectable, bool):
            raise ManifestError(f"{path}.selectable must be a boolean")
        skill = {
            "name": name,
            "stage": stage_value.strip(),
            "description": raw.get("description", ""),
            "keywords": _string_list(
                raw.get("keywords"), f"{path}.keywords", allow_empty=False
            ),
            "inputs": _string_list(
                raw.get("inputs"), f"{path}.inputs", allow_empty=False
            ),
            "outputs": _string_list(
                raw.get("outputs"), f"{path}.outputs", allow_empty=False
            ),
            "acceptance": _string_list(
                raw.get("acceptance"), f"{path}.acceptance", required=False
            ),
            "consumes": _string_list(
                raw.get("consumes"), f"{path}.consumes", required=False
            ),
            "produces": _string_list(
                raw.get("produces"), f"{path}.produces", required=False
            ),
            "requires": _string_list(
                raw.get("requires"), f"{path}.requires", required=False
            ),
            "dependsOn": _string_list(
                raw.get("dependsOn"), f"{path}.dependsOn", required=False
            ),
            "selectable": selectable,
            "index": index,
        }
        # Simple manifests may declare only inputs and outputs. In that case
        # those names double as artifact contracts and later steps are assumed
        # to be chained. Explicit artifact fields are authoritative when present.
        skill["explicitContract"] = any(
            key in raw for key in ("consumes", "produces", "requires")
        )
        skill["inputArtifacts"] = [_artifact_key(item) for item in skill["inputs"]]
        skill["outputArtifacts"] = [_artifact_key(item) for item in skill["outputs"]]
        skill["effectiveConsumes"] = (
            list(skill["consumes"]) or list(skill["inputArtifacts"])
        )
        skill["effectiveProduces"] = (
            list(skill["produces"]) or list(skill["outputArtifacts"])
        )
        skills.append(skill)
        by_name[name] = skill

    for skill in skills:
        for dependency in skill["dependsOn"]:
            if dependency not in by_name:
                raise ManifestError(
                    f"{skill['name']} depends on unknown skill '{dependency}'"
                )
            if not by_name[dependency]["selectable"]:
                raise ManifestError(
                    f"{skill['name']} depends on non-selectable skill '{dependency}'"
                )

    version = data.get("manifestVersion")
    if version is not None and not _is_nonempty_str(version):
        raise ManifestError("manifestVersion must be a non-empty string")
    return {
        "manifestVersion": version.strip() if _is_nonempty_str(version) else None,
        "skills": skills,
        "by_name": by_name,
        "sourcePath": source_path,
    }


def load_manifest(path: str | Path) -> dict:
    data = common.load_json(path)
    try:
        return normalize_manifest(data, source_path=str(Path(path)))
    except ManifestError as exc:
        raise SystemExit(f"Invalid skills manifest: {exc}") from exc


def stage_rank(stage: str) -> int:
    return STAGE_RANK.get(stage, len(STAGE_ORDER))


def skill_priority(skill: dict) -> tuple[int, int]:
    return (stage_rank(skill["stage"]), skill["index"])


def keyword_matches(request_lower: str, keyword: str) -> bool:
    """Match a keyword, using token boundaries for short ASCII tokens."""
    key = keyword.strip().lower()
    if not key:
        return False
    if (
        len(key) <= 4
        and " " not in key
        and "." not in key
        and "-" not in key
        and re.fullmatch(r"[a-z0-9]+", key)
    ):
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])",
                request_lower,
            )
            is not None
        )
    return key in request_lower


def match_skills(request: str, manifest: dict) -> dict[str, list[str]]:
    if not isinstance(request, str) or not request.strip():
        raise RequestError("request must not be empty")
    request_lower = request.lower()
    matched: dict[str, list[str]] = {}
    for skill in manifest["skills"]:
        if not skill["selectable"]:
            continue
        hits = [
            keyword
            for keyword in skill["keywords"]
            if keyword_matches(request_lower, keyword)
        ]
        if hits:
            matched[skill["name"]] = hits
    return matched


def _producer_candidates(manifest: dict, artifact: str, consumer: str) -> list[dict]:
    return [
        skill
        for skill in manifest["skills"]
        if skill["selectable"]
        and skill["name"] != consumer
        and artifact in skill["effectiveProduces"]
    ]


def select_skills(
    request: str, manifest: dict
) -> tuple[dict[str, list[str]], list[str], dict[str, str]]:
    """Return keyword matches, selected skill names and selection reasons."""
    matched = match_skills(request, manifest)
    selected: set[str] = set(matched)
    reasons: dict[str, str] = {name: "keyword" for name in matched}
    by_name = manifest["by_name"]

    changed = True
    while changed:
        changed = False
        for name in list(selected):
            skill = by_name[name]
            for artifact in skill["requires"]:
                if any(
                    other != name
                    and artifact in by_name[other]["effectiveProduces"]
                    for other in selected
                ):
                    continue
                candidates = _producer_candidates(manifest, artifact, name)
                if not candidates:
                    continue
                candidate = sorted(candidates, key=skill_priority)[0]
                if candidate["name"] not in selected:
                    selected.add(candidate["name"])
                    reasons[candidate["name"]] = "artifact_requirement"
                    changed = True
            for dependency in skill["dependsOn"]:
                if dependency not in selected:
                    selected.add(dependency)
                    reasons[dependency] = "dependency"
                    changed = True

    ordered, _ = order_skills(selected, manifest)
    return matched, ordered, reasons


def order_skills(
    selected_names: set[str] | list[str], manifest: dict
) -> tuple[list[str], bool]:
    """Topologically order selected skills, using stage/manifest priority."""
    names = set(selected_names)
    by_name = manifest["by_name"]
    edges: dict[str, set[str]] = {name: set() for name in names}

    for name in names:
        skill = by_name[name]
        for artifact in skill["requires"]:
            for producer in names:
                if artifact in by_name[producer]["effectiveProduces"]:
                    edges[producer].add(name)
        for dependency in skill["dependsOn"]:
            if dependency in names:
                edges[dependency].add(name)

    indegree = {name: 0 for name in names}
    for targets in edges.values():
        for target in targets:
            indegree[target] += 1

    heap: list[tuple[int, int, str]] = []
    for name in names:
        if indegree[name] == 0:
            priority = skill_priority(by_name[name])
            heapq.heappush(heap, (priority[0], priority[1], name))

    ordered: list[str] = []
    while heap:
        _, _, name = heapq.heappop(heap)
        ordered.append(name)
        for target in sorted(edges[name], key=lambda item: skill_priority(by_name[item])):
            indegree[target] -= 1
            if indegree[target] == 0:
                priority = skill_priority(by_name[target])
                heapq.heappush(heap, (priority[0], priority[1], target))

    cycle = len(ordered) < len(names)
    if cycle:
        remaining = sorted(
            names - set(ordered), key=lambda item: skill_priority(by_name[item])
        )
        ordered.extend(remaining)
    return ordered, cycle


def _default_acceptance(skill: dict) -> list[str]:
    return [
        f"{skill['name']} produces the declared outputs: {', '.join(skill['outputs'])}.",
        "Inputs and provenance are recorded; missing information is reported instead of guessed.",
        "The step reports errors and warnings before the next step starts.",
    ]


def build_steps(
    ordered_names: list[str],
    manifest: dict,
    matched: dict[str, list[str]],
    reasons: dict[str, str],
) -> list[dict]:
    by_name = manifest["by_name"]
    steps: list[dict] = []
    for index, name in enumerate(ordered_names):
        skill = by_name[name]
        if skill["explicitContract"]:
            required_artifacts = list(skill["requires"])
            contract_mode = "explicit"
        else:
            # Fallback for simple manifests: every later step's declared inputs
            # are expected to come from an earlier output. The first step's
            # inputs are considered external.
            required_artifacts = [] if index == 0 else list(skill["effectiveConsumes"])
            contract_mode = "inputs_outputs"
        steps.append(
            {
                "step": index + 1,
                "owner": name,
                "stage": skill["stage"],
                "selectionReason": reasons.get(name, "requirement"),
                "matchedKeywords": matched.get(name, []),
                "inputs": list(skill["inputs"]),
                "outputs": list(skill["outputs"]),
                "acceptanceChecks": list(skill["acceptance"])
                or _default_acceptance(skill),
                "artifactContract": contract_mode,
                "requiredArtifacts": required_artifacts,
                "consumedArtifacts": list(skill["effectiveConsumes"]),
                "producedArtifacts": list(skill["effectiveProduces"]),
                "dependsOn": list(skill["dependsOn"]),
            }
        )
    return steps


def validate_handoffs(steps: list[dict]) -> dict:
    """Validate required artifact producers and record ordered handoff links."""
    produced_by: dict[str, dict] = {}
    links: list[dict] = []
    link_keys: set[tuple[int, int, str]] = set()
    errors: list[dict] = []
    warnings: list[dict] = []

    for step in steps:
        for artifact in step["requiredArtifacts"]:
            producer = produced_by.get(artifact)
            if producer is None:
                errors.append(
                    {
                        "code": "BROKEN_HANDOFF",
                        "step": step["step"],
                        "owner": step["owner"],
                        "artifact": artifact,
                        "message": (
                            f"{step['owner']} requires artifact '{artifact}' but no "
                            "earlier step produces it."
                        ),
                    }
                )
                continue
            key = (producer["step"], step["step"], artifact)
            if key not in link_keys:
                link_keys.add(key)
                links.append(
                    {
                        "fromStep": producer["step"],
                        "from": producer["owner"],
                        "toStep": step["step"],
                        "to": step["owner"],
                        "artifacts": [artifact],
                        "kind": "required",
                    }
                )
        for artifact in step["producedArtifacts"]:
            previous = produced_by.get(artifact)
            if previous is not None:
                warnings.append(
                    {
                        "code": "DUPLICATE_ARTIFACT_PRODUCER",
                        "step": step["step"],
                        "owner": step["owner"],
                        "artifact": artifact,
                        "message": (
                            f"Artifact '{artifact}' is produced by both "
                            f"{previous['owner']} (step {previous['step']}) and "
                            f"{step['owner']} (step {step['step']})."
                        ),
                    }
                )
            produced_by[artifact] = step

    for index in range(len(steps) - 1):
        current = steps[index]
        following = steps[index + 1]
        shared = sorted(
            set(current["producedArtifacts"]) & set(following["consumedArtifacts"])
        )
        for artifact in shared:
            key = (current["step"], following["step"], artifact)
            if key in link_keys:
                continue
            link_keys.add(key)
            links.append(
                {
                    "fromStep": current["step"],
                    "from": current["owner"],
                    "toStep": following["step"],
                    "to": following["owner"],
                    "artifacts": [artifact],
                    "kind": "adjacent",
                }
            )

    return {
        "status": "BROKEN" if errors else ("EMPTY" if not steps else "OK"),
        "links": links,
        "errors": errors,
        "warnings": warnings,
    }


def _manifest_info(manifest: dict, manifest_path: str | None) -> dict:
    return {
        "path": manifest_path or manifest.get("sourcePath"),
        "manifestVersion": manifest.get("manifestVersion"),
        "skillCount": len(manifest["skills"]),
        "selectableSkillCount": sum(
            1 for skill in manifest["skills"] if skill["selectable"]
        ),
    }


def _empty_plan(
    request: str,
    manifest: dict,
    manifest_path: str | None,
    allow_empty: bool,
) -> dict:
    errors = []
    warnings = []
    status = "EMPTY"
    if not allow_empty:
        status = "FAILED"
        errors.append(
            {
                "code": "NO_SKILL_MATCH",
                "message": (
                    "No skill keyword matched the request. Clarify the task or "
                    "extend the manifest keywords."
                ),
            }
        )
    else:
        warnings.append(
            {
                "code": "NO_SKILL_MATCH",
                "message": (
                    "No skill matched the request; an empty plan was produced "
                    "because --allow-empty was set."
                ),
            }
        )
    return {
        "planVersion": "0.1",
        "status": status,
        "request": request,
        "manifest": _manifest_info(manifest, manifest_path),
        "classification": {
            "matchedStages": [],
            "plannedStages": [],
            "keywordMatches": {},
            "autoSelected": {},
        },
        "selectedSkills": [],
        "steps": [],
        "handoffValidation": {
            "status": "EMPTY",
            "links": [],
            "errors": [],
            "warnings": [],
        },
        "errors": errors,
        "warnings": warnings,
        "limitations": list(LIMITATIONS),
    }


def build_task_plan(
    request: str,
    manifest: dict,
    manifest_path: str | None = None,
    allow_empty: bool = False,
) -> dict:
    """Build a deterministic task plan for a request and manifest."""
    if not isinstance(request, str) or not request.strip():
        raise RequestError("request must not be empty")

    matched, ordered_names, reasons = select_skills(request, manifest)
    if not ordered_names:
        return _empty_plan(request, manifest, manifest_path, allow_empty)

    ordered, cycle = order_skills(ordered_names, manifest)
    steps = build_steps(ordered, manifest, matched, reasons)
    handoff = validate_handoffs(steps)

    by_name = manifest["by_name"]
    matched_stages: list[str] = []
    for skill in sorted(
        (by_name[name] for name in matched), key=skill_priority
    ):
        if skill["stage"] not in matched_stages:
            matched_stages.append(skill["stage"])
    planned_stages: list[str] = []
    for step in steps:
        if step["stage"] not in planned_stages:
            planned_stages.append(step["stage"])

    errors: list[dict] = []
    if cycle:
        errors.append(
            {
                "code": "DEPENDENCY_CYCLE",
                "message": "The selected skills contain a dependency cycle.",
            }
        )
    errors.extend(handoff["errors"])
    warnings = list(handoff["warnings"])

    return {
        "planVersion": "0.1",
        "status": "FAILED" if errors else "READY",
        "request": request,
        "manifest": _manifest_info(manifest, manifest_path),
        "classification": {
            "matchedStages": matched_stages,
            "plannedStages": planned_stages,
            "keywordMatches": matched,
            "autoSelected": {
                name: reason
                for name, reason in reasons.items()
                if reason != "keyword"
            },
        },
        "selectedSkills": ordered,
        "steps": steps,
        "handoffValidation": handoff,
        "errors": errors,
        "warnings": warnings,
        "limitations": list(LIMITATIONS),
    }


def render_markdown(plan: dict) -> str:
    manifest = plan["manifest"]
    classification = plan["classification"]
    lines = [
        "# Mine Project Orchestration Report",
        "",
        f"- **Status**: {plan['status']}",
        f"- **Request**: {plan['request']}",
        f"- **Manifest**: `{manifest.get('path') or '-'}` "
        f"({manifest.get('skillCount', 0)} skills)",
        f"- **Selected skills**: "
        f"{', '.join(plan['selectedSkills']) or 'none'}",
        f"- **Matched stages**: "
        f"{', '.join(classification.get('matchedStages', [])) or 'none'}",
        f"- **Planned stages**: "
        f"{', '.join(classification.get('plannedStages', [])) or 'none'}",
    ]

    auto_selected = classification.get("autoSelected") or {}
    if auto_selected:
        lines.append(
            "- **Added by contract**: "
            + ", ".join(f"{name} ({reason})" for name, reason in auto_selected.items())
        )

    lines.extend(
        [
            "",
            "## Task Plan",
            "",
            "| Step | Owner skill | Stage | Selection | Inputs | Outputs |",
            "|---:|---|---|---|---|---|",
        ]
    )
    if plan["steps"]:
        for step in plan["steps"]:
            lines.append(
                f"| {step['step']} | `{step['owner']}` | {step['stage']} | "
                f"{step['selectionReason']} | {'; '.join(step['inputs'])} | "
                f"{'; '.join(step['outputs'])} |"
            )
    else:
        lines.append("| - | - | - | - | - | - |")

    for step in plan["steps"]:
        lines.extend(
            [
                "",
                f"### Step {step['step']} — {step['owner']}",
                "",
                f"- **Stage**: {step['stage']}",
                f"- **Inputs**: {'; '.join(step['inputs'])}",
                f"- **Outputs**: {'; '.join(step['outputs'])}",
                f"- **Required artifacts**: "
                f"{', '.join(step['requiredArtifacts']) or 'none'}",
                f"- **Produced artifacts**: "
                f"{', '.join(step['producedArtifacts']) or 'none'}",
                "- **Acceptance checks**:",
            ]
        )
        lines.extend(f"  - {check}" for check in step["acceptanceChecks"])

    handoff = plan["handoffValidation"]
    lines.extend(
        [
            "",
            "## Handoff Validation",
            "",
            f"- **Status**: {handoff['status']}",
            "",
            "| From | To | Artifact | Kind |",
            "|---|---|---|---|",
        ]
    )
    if handoff["links"]:
        for link in handoff["links"]:
            lines.append(
                f"| {link['fromStep']}. `{link['from']}` | "
                f"{link['toStep']}. `{link['to']}` | "
                f"{', '.join(link['artifacts'])} | {link['kind']} |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.extend(["", "## Errors", ""])
    if plan["errors"]:
        for error in plan["errors"]:
            location = f" (step {error['step']})" if "step" in error else ""
            lines.append(f"- `{error['code']}`{location} — {error['message']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if plan["warnings"]:
        for warning in plan["warnings"]:
            location = f" (step {warning['step']})" if "step" in warning else ""
            lines.append(f"- `{warning['code']}`{location} — {warning['message']}")
    else:
        lines.append("- None")

    sources = plan.get("sources") or {}
    if sources:
        lines.extend(["", "## Sources", ""])
        for label, source in sources.items():
            lines.append(
                f"- **{label}**: `{source.get('path', '-')}` "
                f"(SHA-256 `{source.get('sha256', '-')}`)"
            )

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in plan["limitations"])
    lines.extend(
        [
            "",
            "> This plan is advisory. The orchestrator does not execute skills, "
            "fetch data or create models in v0.1.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(plan: dict, out_dir: str) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "task_plan.json"
    markdown_path = out / "orchestration_report.md"
    common.write_json(json_path, plan)
    common.write_text(markdown_path, render_markdown(plan))
    return {"json": str(json_path), "markdown": str(markdown_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan a mine 3D request across the Open Mining Skills."
    )
    parser.add_argument("request", help="User request text to classify")
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to skills_manifest.json (default: references/skills_manifest.json)",
    )
    parser.add_argument(
        "--out-dir",
        default="orchestration_output",
        help="Directory for task_plan.json and orchestration_report.md",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit 0 and emit an empty plan when no skill matches.",
    )
    args = parser.parse_args(argv)

    try:
        manifest_data = common.load_json(args.manifest)
        manifest = normalize_manifest(manifest_data, source_path=str(Path(args.manifest)))
        plan = build_task_plan(
            args.request,
            manifest,
            manifest_path=args.manifest,
            allow_empty=args.allow_empty,
        )
        manifest_source = common.source_manifest(args.manifest)
    except ManifestError as exc:
        print(f"Invalid skills manifest: {exc}", file=sys.stderr)
        return 2
    except RequestError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2

    plan["sources"] = {"manifest": manifest_source}
    paths = write_outputs(plan, args.out_dir)

    print(
        f"Orchestration: {plan['status']} — {len(plan['selectedSkills'])} skill(s) "
        f"selected, handoff {plan['handoffValidation']['status']}."
    )
    if plan["selectedSkills"]:
        print("Selected: " + " -> ".join(plan["selectedSkills"]))
    for error in plan["errors"][:10]:
        print(f"  ERROR {error['code']}: {error['message']}")
    print("Outputs: " + ", ".join(paths.values()))

    return 1 if plan["status"] == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(main())
