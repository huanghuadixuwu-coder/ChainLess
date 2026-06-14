# Local Browser QA Report

- Run ID: `2026-06-06T14-56-50-428Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31`
- Final URL: `http://118.196.142.31/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps

- PASS auth-login
- PASS conversation-create
- PASS conversation-rename
- PASS conversation-archive
- PASS chat-sse
- PASS tool-card-web-fetch
- PASS right-panel-files
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 1

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-56-50-428Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-56-50-428Z\01-auth-login.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-56-50-428Z\02-chat-sse.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-56-50-428Z\03-tool-panel.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-56-50-428Z\failure.png`

## Suite Error

```
locator.waitFor: Error: strict mode violation: getByText('42', { exact: true }) resolved to 2 elements:
    1) <pre class="mt-3 overflow-x-auto rounded-md px-3 py-2 text-xs bg-zinc-950 text-zinc-300">42</pre> aka getByText('42').nth(1)
    2) <pre class="overflow-x-auto rounded-lg bg-zinc-950 px-3 py-3 text-xs text-zinc-300">42</pre> aka getByRole('complementary').getByText('42')

Call log:
[2m  - waiting for getByText('42', { exact: true }) to be visible[22m

    at runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:252:49)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:331:19)
```

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31/api/v1/conversations/7356032e-95bd-4e44-ab84-7db8685fd0af",
    "errorText": "net::ERR_ABORTED"
  }
]
```
