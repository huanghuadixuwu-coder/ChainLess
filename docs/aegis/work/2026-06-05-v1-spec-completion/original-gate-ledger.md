# Original Gate Ledger

**Updated**: 2026-06-15  
**Runtime**: local Docker Desktop, compose-managed Nginx at `http://localhost`  
**Boundary**: this ledger maps the 2026-06-02 P1-P6 gates and explicit
`Verify:` steps to W11 evidence. It does not claim live external services when
credentials were not configured.

## External Proof Boundaries

| Boundary | Current fact | W11 treatment |
|---|---|---|
| Live GLM-4.5 Air API call | `GLM_API_KEY_SET|False`, `default_providers|0`, `all_providers|0` in the local Docker runtime | The OpenAI-compatible provider path, SSE, tool calls, and browser chat are verified with disposable mock providers. No live GLM API call is claimed. |
| Real Feishu group receipt | No real Feishu webhook/secret was supplied | Feishu-compatible delivery was previously verified against a live receiver; real group receipt remains credential-dependent. |

## P1-P6 Gates

| Gate | Original requirement | Status | Evidence |
|---|---|---|---|
| P1 Foundation | Login, create conversation, send chat, receive SSE streaming response from GLM-4.5 Air | Verified for product/runtime path; live GLM external proof not configured | Windows Chrome `spec-complete` QA passed through `http://localhost`; `spec_complete_probe.py` verified auth/login/refresh/me, SSE `text`/`done`, and temporary OpenAI-compatible provider chat calls. Live GLM is not claimed because no GLM key/default provider exists. |
| P2 Agent Engine + Sandbox | Agent generates code, sandbox executes, result streams back; `shell_exec date`; `rm -rf /` asks confirmation and denial proposes alternative; sandbox pool visible | Verified | `spec_complete_probe.py` verified Code-as-Action Fibonacci SSE events and destructive denial persistence. `performance_probe.py --scenario fibonacci` returned exact stdout `55` with sandbox allocate/complete/delete. `production_boundary_probe.py` returned sandbox output `42` and healthy pool data. Browser `spec-complete` verified `code_as_action` and destructive confirmation denial in UI. |
| P3 Tool Ecosystem | Register MCP server, agent calls tool, result appears in chat | Verified | `spec_complete` eval passed the filesystem MCP discovery/invocation task, and full backend tests include MCP stdio, HTTP/SSE, idle/reconnect/failure, risk-default, and tenant scoping coverage. Browser `spec-complete` verified Settings MCP register/test/cleanup. |
| P4 Memory System | Create memories across types, layered instructions and relevant memories merge into session; pgvector semantic query works | Verified | W8 evidence closed five typed memory rows with real 1536-dimensional pgvector embeddings and cosine-distance ordering. Browser `spec-complete` verified Settings memory create/search/merge/cleanup and rich-input attachment context injection. Full backend tests remained green. |
| P5 Eval + Channel + Scheduler | Eval passes; cron task fires; Feishu webhook receives message | Verified within available credentials | `run-eval.py --suite basic --json --min-pass-rate 1.0` passed `10 / 10`; `run-eval.py --suite spec_complete --json --min-pass-rate 1.0` passed `4 / 4`. W8 Feishu-compatible receiver evidence remains the credential-ready delivery proof; real Feishu group receipt needs user-supplied credentials. |
| P6 Polish + Production | `docker-compose up`, system health green, frontend login, keyboard shortcuts, errors, dark mode, valid backup | Verified | Fresh `docker-compose up -d --build` converged locally. Public health and Nginx-to-backend health returned `{"status":"ok"}`. `clean_start_probe.py`, `production_boundary_probe.py`, backup, isolated restore drill, full backend tests, frontend lint/build, and Windows Chrome `spec-complete` all exited successfully. |

## Explicit Verify Steps

| Source line topic | Original verify intent | W11 disposition |
|---|---|---|
| Compose startup | `docker-compose up -d` and `docker-compose ps` | Fresh `docker-compose up -d --build` succeeded; `docker-compose ps` showed canonical production services up/healthy where applicable. |
| Backend health restart/curl | Restart backend and curl health | Fresh rebuild/recreate was followed by public health and in-container Nginx-to-backend health, both returning `{"status":"ok"}`. |
| LLM gateway GLM stream | Register GLM-4.5 Air, stream chunks | Provider contract verified with disposable OpenAI-compatible providers in API/browser. Live GLM proof is external-credential blocked in the current runtime. |
| Conversation SSE curl/browser | Create conversation, send message, observe SSE | `spec_complete_probe.py` and Windows Chrome `spec-complete` both verified chat SSE. |
| Builtin tool function schema | Import and assert OpenAI-compatible function schemas | `spec_complete` eval passed `builtin-tool-openai-schema-contract`; backend test suite passed. |
| Code-as-Action Fibonacci | Sandbox code returns Fibonacci result | W11 performance probe returned exact stdout `55`. |
| MCP filesystem server | Register filesystem MCP and call `mcp__fs__list_directory` | `spec_complete` eval discovered and invoked `mcp__fs__list_directory`. |
| Layered instruction merge | User/project instruction files merge in priority order | W7/W8 backend and browser evidence remains closed; full backend tests passed in W11. |
| Memory semantic recall | Semantic search returns coding preference | W8 memory gate remains closed; W11 full backend tests and browser settings memory flow passed. |
| Eval runner | `basic` eval JSON passes threshold | W11 `basic` eval passed `10 / 10` at `min_pass_rate=1.0`. |
| Feishu cron | Scheduled task delivers to webhook | W8 live receiver evidence remains the available proof; real Feishu group receipt requires credentials. |
| Seed/login after clean start | Startup seed login-ready | W11 `clean_start_probe.py` returned migrations `head`, seed `idempotent`, and `login_ready: true`. |
| Unified errors | 404, 401, 500 use error envelope | W11 `spec_complete_probe.py` verified representative auth, forbidden, and not-found envelopes; full backend tests passed. |
| Rate limit | Burst requests eventually return `429` | W9/W10 rate-limit evidence remains closed; W11 full backend tests passed and browser QA had zero unexpected `429`. |
| System health | DB, Redis, sandbox pool health green | W11 public health, admin production boundary health, metrics, and sandbox pool checks passed. |
| Frontend polish | Code block, terminal output, tool card, keyboard shortcuts, dark mode | Windows Chrome `spec-complete` verified code output, tool panel, files/diff, markdown fold/copy, virtual scroll, keyboard shortcuts, and theme toggle without style rewrite. |
| Backup/restore | Backup creates valid dump; restore procedure works | W11 backup produced `/backups/chainless-20260615-061030.sql` (212K); restore drill restored and queried an isolated temporary database, then cleaned it. |

## Final W11 Evidence Summary

- Backend: `339 passed, 4 skipped, 3 warnings`.
- Frontend: `npm run lint` exit `0`; `npm run build` exit `0`.
- Browser: `.gstack/qa-reports/local/spec-complete-2026-06-15T06-13-38-067Z`, `ok: true`.
- API probe: `spec_complete_probe.py`, `ok: true`, cleanup residue zero.
- Eval: `basic` `10 / 10`; `spec_complete` `4 / 4`.
- Restore drill: `ok: true`, isolated restored DB dropped and dump removed.
- Performance: HN top-10 Code-as-Action max `757.6ms`; Fibonacci exact `55`.
- Cleanup: Postgres QA-prefix residue counts returned zero; Redis scan showed no QA-prefix keys.
