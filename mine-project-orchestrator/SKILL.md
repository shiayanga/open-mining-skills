---
name: mine-project-orchestrator
description: Route mine 3D and digital twin tasks to the right skills, plan workflows and enforce handoff contracts without loading every skill at once. Use when a request spans multiple mine skills or needs end-to-end task planning.
---

# Mine Project Orchestrator

> Status: v0.1 — manifest-driven keyword routing, minimal skill selection, topological ordering, task-plan generation and handoff validation are implemented with tests. The orchestrator plans only; it does not execute skills, fetch data or dispatch subagents.

## Role

You are the project orchestrator for the Open Mining Skills suite. Your job is to select the smallest set of skills that can complete a task, sequence them and verify their handoffs.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `skills_manifest.json` | Validated: skill name, stage, keywords, inputs, outputs, acceptance checks and optional artifact contracts |
| User request string | Classified by literal keyword matching; unknown requests fail unless `--allow-empty` |
| Default manifest | `references/skills_manifest.json` covers the 17 skills in this repository |
| Handoff contracts | Required artifacts must be produced by an earlier selected step |
| Project state / previous runs | Not consumed in v0.1 |
| Skill execution | Not performed; the output is an advisory plan |

## Quick Start

Run the following commands from this skill directory. The orchestrator uses the Python standard library only.

```bash
python3 scripts/orchestrate.py "解析这个 DXF 文件并重建地形"
# Writes task_plan.json and orchestration_report.md
# to ./orchestration_output/.
```

Digital twin request:

```bash
python3 scripts/orchestrate.py \
  "建设矿山数字孪生：人员定位、安全监测、机械设备管理、三维绑定、点击交互" \
  --out-dir output/digital_twin_plan
```

Exit code `0` for a ready or explicitly allowed empty plan, `1` when no skill matches or a handoff is broken, `2` for an invalid manifest structure or empty request.

## Options

| Option | Default | Meaning |
|---|---|---|
| `request` | required | User request text to classify |
| `--manifest` | `references/skills_manifest.json` | Skills manifest path |
| `--out-dir` | `orchestration_output` | Output directory for plan and report |
| `--allow-empty` | off | Emit an empty plan and exit `0` when no keyword matches |

## Workflow

1. Load and validate the skills manifest; reject duplicate names, missing fields and unknown dependencies.
2. Match request keywords literally, using token boundaries for short ASCII keywords.
3. Select every matching skill, then add required upstream producers for declared `requires` artifacts.
4. Resolve explicit `dependsOn` links; do not add producers for optional inputs.
5. Topologically order the selected skills, breaking ties by stage order and manifest position.
6. Build one step per skill with owner, inputs, outputs, acceptance checks and artifact contracts.
7. Validate handoffs: every required artifact must be produced by a strictly earlier step.
8. Write `task_plan.json` and `orchestration_report.md`; fail on a broken chain.
9. Stop and report ambiguities instead of silently adding unrelated skills.

## Engineering Rules

- Do not duplicate a skill's logic inside the orchestrator.
- Require explicit inputs for every step; no implicit assumptions about CRS, units or scope.
- Preserve provenance from source file to final output.
- Stop the workflow when a quality gate or handoff fails.
- Prefer the fewest skills and the shortest path that satisfies the request.
- The orchestrator produces a plan only; it does not execute skills or fabricate their outputs.
- Keyword matching is literal. When the request is ambiguous, ask for clarification rather than selecting every skill.
- A broken artifact chain is an error, not a warning.

## Quality Requirements

- Every step has an owner skill, inputs, outputs and acceptance checks.
- No required artifact is produced after its consumer; broken chains are reported with the failing artifact.
- The selected set contains only keyword matches and transitively required producers/dependencies.
- The plan is deterministic for the same request, manifest and options.
- The run records the manifest path and SHA-256 so the plan can be audited.
- The default manifest stays aligned with the repository's 17 skills.

## Deliverables

- `task_plan.json`
- `orchestration_report.md`

## Project Layout

- `scripts/orchestrate.py` — manifest validation, routing, ordering, handoff validation and CLI
- `scripts/common.py` — JSON I/O, hashing and formatting helpers
- `references/skills_manifest.json` — default manifest for all 17 skills
- `references/orchestration-guide.md` — manifest schema, selection algorithm, handoff rules and limitations
- `tests/test_orchestrate.py` — unittest suite covering default manifest, routing, handoff failure and CLI

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Run from this skill directory. No third-party packages are required.

## Related Skills

- All modeling, visualization and digital twin skills in this repository
- `mine-data-inspection` — first intake step for raw data
- `mine-model-quality-check` — the default quality gate between stages
