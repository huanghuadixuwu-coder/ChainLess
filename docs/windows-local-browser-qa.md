# Windows Local Browser QA

This project can now run a local Windows browser smoke/QA pass without relying on:

- local Python
- system Node/npm
- remote browser screenshots

It uses:

- local Chrome or Edge on Windows
- the Codex bundled Node runtime
- the Codex bundled `playwright` package
- the local Docker Chainless URL you want to test

## Why this exists

This is the missing browser execution path needed before a fuller `/qa` workflow is practical on this machine.

It is especially useful when:

- the app runs in local Docker but browser automation must happen on Windows
- browser automation must happen locally
- the machine does not have a normal Node/npm install

## Quick start

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-browser-qa.ps1 -Url "http://localhost" -Browser chrome
```

Before running longer QA flows, read:

```text
docs/remote-windows-runtime-notes.md
```

It records the PowerShell quoting, Docker rebuild, locator, and test cleanup
pitfalls that have already cost time in this project. Remote-server notes are
historical only; current runtime verification must use local Docker Desktop.

Headless run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-browser-qa.ps1 -Url "http://localhost" -Browser chrome -Headless
```

Use Edge instead of Chrome:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-browser-qa.ps1 -Url "http://localhost" -Browser msedge
```

Keep the browser open after the scripted checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-browser-qa.ps1 -Url "http://localhost" -Browser chrome -KeepOpen
```

Settings suite with separate chat credentials:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-browser-qa.ps1 `
  -Url "http://localhost" -Browser chrome -Headless -Suite settings `
  -TimeoutMs 120000 -Tenant "<temporary-tenant>" `
  -Username "<admin-user>" -Password "<redacted>" `
  -ChatUsername "<chat-admin-user>" -ChatPassword "<redacted>"
```

Use separate admin/chat users for the full Settings suite so the final chat
proof does not reuse the same rate-limit bucket as the high-volume settings
panel flow.

## What the script does

The launcher calls `scripts/windows-browser-qa.cjs`, which:

1. launches local Chrome or Edge through Playwright
2. opens the target URL
3. waits for initial load
4. checks whether the text `Loading` disappears
5. optionally runs route-aware suites such as `settings`
6. captures:
   - console errors
   - page errors
   - failed network requests
7. writes screenshots and reports

## Output

Artifacts are written under:

```text
.gstack/qa-reports/local/<suite>-<timestamp>/
```

Each run produces:

- one or more screenshots
- `report.json`
- `report.md`

## Current scope

This is a strong local browser execution path, but it is not a direct
replacement for standard `gstack /qa` when the working tree is dirty.
Standard `/qa` requires a clean tree so it can create one atomic commit per
fix; the current V1 completion branch intentionally contains multi-workstream
uncommitted changes.

What it already gives us:

- repeatable browser launch on Windows
- visible or headless local browser testing
- screenshot capture
- JS/runtime/network smoke checks
- basic stuck-loading detection
- login/chat/conversation smoke checks
- Workstream 10 browser regression flow
- Workstream 5 Settings flow covering provider, agent, tools/MCP, memories,
  Feishu channel, proactive tasks, passive skills, eval, system/theme, context
  banner, provider switch proof, and cleanup
- false-positive filtering for only Next.js `_rsc` requests aborted with
  `net::ERR_ABORTED`; all other request failures still fail the report

## Recommended next step

Use this against `http://localhost` after the local Docker stack is healthy.
For full `/qa` semantics, first get the branch to a clean committed state or
use a disposable worktree so gstack can safely create one commit per fix.
