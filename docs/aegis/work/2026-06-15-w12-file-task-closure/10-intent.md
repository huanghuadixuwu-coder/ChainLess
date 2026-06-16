# W12 File Task Closure Intent

Created: 2026-06-15
Parent spec: `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
Parent plan: `docs/aegis/plans/2026-06-15-w12-file-task-closure-execution-plan.md`

## Requested Outcome

Close the Chainless file task loop: upload -> explicit file state -> sent
message attachment -> agent-readable clean run workspace -> generated artifact
-> preview/download -> fail-closed if attachment input is unavailable.

## Scope

- Backend artifact download API.
- Message attachment metadata serialization.
- Run-scoped workspace materialization.
- File tool per-run workspace scoping.
- Chat runtime integration and attachment fail-closed behavior.
- Frontend file states, sent attachment cards, Files download action, and
  Settings sidebar navigation.
- Browser QA suite and cleanup.
- Problem ledger and evidence updates.

## Non-Goals

- No frontend visual redesign.
- No host Python/Node app runtime.
- No broad weather/search/booking tool contract claim.
- No binary upload support.
- No commits without explicit user request.

## BaselineReadSetHint

- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/plans/2026-06-15-w12-file-task-closure-execution-plan.md`
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `AGENTS.md`

## ImpactStatementDraft

The work touches public API shape, artifact source-of-truth boundaries, agent
runtime file access, tool execution context, frontend message rendering, and
browser QA. The key architecture boundary is artifact storage as canonical
source and `/workspace/runs/<run_id>` as derived runtime view.
