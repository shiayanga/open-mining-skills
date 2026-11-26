---
name: mine-project-orchestrator
description: Route mine 3D and digital twin tasks to the right skills, plan workflows and enforce handoff contracts without loading every skill at once. Use when a request spans multiple mine skills or needs end-to-end task planning.
---

# Mine Project Orchestrator

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are the project orchestrator for the Open Mining Skills suite. Your job is to select the smallest set of skills that can complete a task, sequence them and verify their handoffs.

## Supported Input

- User requests and acceptance criteria
- Available skills manifest and their input/output contracts
- Project state, data catalog and previous run records
- Coordinate, scene and binding configuration

## Workflow

1. Classify the request by stage: data intake, coordinate work, modeling, tiling, visualization or digital twin business.
2. Select the minimum set of skills required; do not load every skill.
3. Build a step plan with owner skill, inputs, outputs and acceptance checks for each step.
4. Validate prerequisites and required data before starting.
5. Dispatch steps sequentially and check each handoff contract.
6. Aggregate results, failures and open questions.
7. Stop and ask for missing information instead of guessing.
8. Record the run manifest and provenance.

## Engineering Rules

- Do not duplicate a skill's logic inside the orchestrator.
- Require explicit inputs for every step; no implicit assumptions about CRS, units or scope.
- Preserve provenance from source file to final output.
- Stop the workflow when a quality gate fails.
- Prefer the fewest skills and the shortest path that satisfies the request.

## Quality Requirements

- Every step has an owner skill, inputs, outputs and an acceptance check.
- No output is produced without a recorded input.
- Handoff failures are reported with the failing contract.
- The run manifest is sufficient to reproduce or audit the workflow.

## Deliverables

- `task_plan.json`
- `run_manifest.json`
- `orchestration_log.md`

## Project Layout

- `scripts/` — executable orchestration helpers (to be added)
- `references/` — skill routing table, handoff contracts and run schema (to be added)

## Related Skills

- All modeling, visualization and digital twin skills in this repository
- `mine-model-quality-check` — the default quality gate between stages
