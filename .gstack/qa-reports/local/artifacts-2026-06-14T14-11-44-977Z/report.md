# Local Browser QA Report

- Run ID: `2026-06-14T14-11-44-977Z`
- Suite: `artifacts`
- URL: `http://localhost`
- Final URL: `http://localhost/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps

- PASS auth-login
- PASS mock-provider-default
- PASS conversation-create
- PASS chat-file-write-tool
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 0
- Ignored request failures: 0
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-11-44-977Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-11-44-977Z\failure.png`

## Suite Error

```
locator.waitFor: Error: strict mode violation: getByText('w6/w6-artifacts-1781446305266.py') resolved to 5 elements:
    1) <p class="whitespace-pre-wrap text-sm">Create the W6 artifact file w6/w6-artifacts-17814…</p> aka getByText('Create the W6 artifact file')
    2) <pre class="mt-3 overflow-x-auto rounded-md bg-zinc-950 px-3 py-2 text-xs text-zinc-400">{↵  "path": "w6/w6-artifacts-1781446305266.py",↵ …</pre> aka getByText('{ "path": "w6/w6-artifacts-')
    3) <pre class="mt-3 overflow-x-auto rounded-md px-3 py-2 text-xs bg-zinc-950 text-zinc-300">Written 42 bytes to workspace:w6/w6-artifacts-178…</pre> aka getByText('Written 42 bytes to workspace')
    4) <p class="truncate text-xs font-medium">w6/w6-artifacts-1781446305266.py</p> aka getByTestId('artifact-row')
    5) <p class="truncate text-xs font-medium text-zinc-200">w6/w6-artifacts-1781446305266.py</p> aka getByText('w6/w6-artifacts-1781446305266').nth(4)

Call log:
[2m  - waiting for getByText('w6/w6-artifacts-1781446305266.py') to be visible[22m

    at runArtifacts (E:\Chainless\scripts\windows-browser-qa.cjs:805:58)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:1225:19)
```
