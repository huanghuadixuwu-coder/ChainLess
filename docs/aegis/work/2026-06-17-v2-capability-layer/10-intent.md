# V2 Capability Operating Layer Implementation Intent

Date: 2026-06-17
Branch: codex/v2-capability-layer
Parent plan source: E:/Chainless/docs/aegis/plans/2026-06-17-v2-capability-operating-layer-execution-plan.md
Approved spec source: E:/Chainless/docs/aegis/specs/2026-06-16-v2-capability-operating-layer-design.md

## Requested Outcome

Implement the V2 Capability Operating Layer using Subagent-Driven Development:
private Capability Candidates, durable analysis outbox, private Memory/Skill
acceptance, Agent-callable Workers, policy guards, hooks, UI Inbox/Settings
surfaces, eval, Windows browser QA, and cleanup evidence.

## Scope

- Execute W1-W9 from the reviewed V2 execution plan.
- Use local Docker Desktop only for runtime and tests.
- Use one fresh subagent per implementation slice and release it after review.
- Preserve frontend visual style and existing V1/W12 behavior.

## Non-Goals

- No commits unless the user explicitly requests them.
- No frontend redesign or global style changes.
- No team capability publishing, marketplace, arbitrary user hooks, or full
  admin Managed Settings in this phase.
- No host Python or host Node as application runtime.

## Baseline Read Set

- Parent plan source listed above.
- Approved spec source listed above.
- `AGENTS.md`
- `backend/app/models/memory.py`
- `backend/app/models/skill.py`
- `backend/app/api/v1/conversations.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/agent/engine.py`
- `backend/app/core/agent/tool_router.py`
- `frontend/src/components/chat/preview-panel.tsx`
- `frontend/src/components/settings/settings-shell.tsx`
- `scripts/windows-browser-qa.cjs`

## Impact Statement

This work touches durable architecture surfaces: public API paths, persistence
models, migrations, Agent runtime context, tool policy, user-private capability
scope, Worker execution, UI surfaces, eval, and QA evidence.

## Stop Condition

V2 phase 1 is complete only after W9 final verification passes and
`PROBLEM_TODO_LIST.md` has no unresolved V2 item discovered during execution.
