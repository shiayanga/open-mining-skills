# Orchestration Guide

`scripts/orchestrate.py` plans a mine 3D or digital twin request against
`references/skills_manifest.json`. It selects the smallest set of skills that
satisfies the request, orders them, and validates artifact handoffs. It does not
execute any skill.

## Default stage order

```text
intake -> parse -> coordinate -> modeling -> tiling -> integration
       -> digital-twin -> visualization -> interaction -> quality -> orchestration
```

Custom stages are accepted but sorted after the documented stages and then by
manifest position. The stage is a planning label, not a hard gate.

## Manifest schema

```json
{
  "manifestVersion": "0.1",
  "skills": [
    {
      "name": "mine-data-inspection",
      "stage": "intake",
      "description": "Inspect raw mine files.",
      "keywords": ["数据检查", "dxf", "xyz"],
      "inputs": ["raw DWG/DXF/XYZ files"],
      "outputs": ["data_inspection_report.json"],
      "acceptance": ["Extents and coordinate clues are reported without guessing."],
      "consumes": [],
      "produces": ["inspection_report"],
      "requires": [],
      "dependsOn": [],
      "selectable": true
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Unique skill directory name. |
| `stage` | yes | Planning stage; use the default stages when possible. |
| `description` | no | Human-readable purpose. |
| `keywords` | yes | Literal request keywords (Chinese substrings or ASCII tokens). |
| `inputs` | yes | Human-readable expected inputs. |
| `outputs` | yes | Human-readable produced files or artifacts. |
| `acceptance` | no | Step-specific acceptance checks; generic checks are generated if absent. |
| `consumes` | no | Artifact types this skill can consume, including external inputs. |
| `produces` | no | Artifact types this skill creates. |
| `requires` | no | Artifact types that must be produced by an earlier selected skill. |
| `dependsOn` | no | Skill names that must be selected first. |
| `selectable` | no | Defaults to `true`; the orchestrator itself is `false`. |

`keywords`, `inputs` and `outputs` must be non-empty. All list entries must be
non-empty strings. `dependsOn` must reference existing selectable skills.

A manifest may use only the core fields (`name`, `stage`, `keywords`, `inputs`,
`outputs`). In that case each step's outputs double as its produced artifacts,
and a later step's inputs are treated as required handoffs; the first step's
inputs are external. For finer control, declare `consumes`, `produces` and
`requires`; those fields are then authoritative and optional inputs do not have
to be produced by an earlier step.

## Request classification and selection

1. Lowercase the request.
2. Match each keyword literally. Short ASCII keywords (up to 4 characters) use
   token boundaries so `tin` does not match `testing`; Chinese keywords use
   substring matching.
3. Select every selectable skill with at least one keyword hit.
4. Resolve `requires`: for every selected consumer, add the highest-priority
   producer of each required artifact. Producers already selected satisfy the
   requirement.
5. Resolve `dependsOn` transitively.
6. Do not add producers for optional `consumes` entries. This keeps the plan
   minimal; external inputs are allowed.
7. Topologically order the selected skills. Stage rank and manifest position
   break ties, so an upstream binding or inspection step moves before its
   consumer even if it appears later in the manifest.

## Handoff validation

A required artifact must be produced by a strictly earlier step. The validator
records `{fromStep, from, toStep, to, artifacts, kind}` links and fails the plan
with `BROKEN_HANDOFF` when no earlier producer exists. Adjacent steps also get
an `adjacent` link when the previous step produces an artifact the next step
consumes, even if it is not declared as `requires`. Each step records whether
its contract came from explicit artifact fields or from the inputs/outputs
fallback.

`handoffValidation.status` is `OK`, `BROKEN` or `EMPTY`. Duplicate producers of
the same artifact produce a warning but do not fail the plan.

## Plan status

| Status | Meaning | CLI exit |
|---|---|---|
| `READY` | Skills selected, no cycle and all required handoffs satisfied. | `0` |
| `EMPTY` | No skill matched and `--allow-empty` was supplied. | `0` |
| `FAILED` | No match, a required handoff is broken, or a dependency cycle exists. | `1` |

`task_plan.json` contains:

- `request`, `manifest`, `classification` (matched/planned stages, keyword hits
  and auto-selected skills).
- `selectedSkills` in execution order.
- `steps`: owner, stage, selection reason, matched keywords, inputs, outputs,
  acceptance checks, artifact-contract mode, required/consumed/produced
  artifacts and dependencies.
- `handoffValidation`: status, links, errors and warnings.
- `errors`, `warnings`, `limitations` and, when run through the CLI, `sources`
  with the manifest SHA-256.

`orchestration_report.md` is the human-readable rendering of the same plan.

## Examples

```bash
python3 scripts/orchestrate.py "解析这个 DXF 文件并重建地形"
# mine-data-inspection -> mine-cad-parser -> mine-terrain-modeling

python3 scripts/orchestrate.py \
  "建设矿山数字孪生：人员定位、安全监测、机械设备管理、三维绑定、点击交互"
# mine-3d-entity-binding -> mine-personnel-tracking
# -> mine-safety-monitoring -> mine-machinery-management
# -> mine-scene-interaction
```

## v0.1 limits

- Literal keyword matching; no LLM classification or negation handling.
- No execution, scheduling, retries or parallel branches.
- Optional inputs and external artifacts are not verified.
- Only declared required artifact handoffs are validated.
- The default manifest lists 17 skills in this repository; new skills must be
  added to the manifest manually.
- Duplicate producers and ambiguous keywords require human review.
