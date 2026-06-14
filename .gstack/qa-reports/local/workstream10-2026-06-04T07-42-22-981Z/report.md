# Local Browser QA Report

- Run ID: `2026-06-04T07-42-22-981Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31:3000`
- Final URL: `http://118.196.142.31:3000/chat`
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
- PASS code-as-action
- FAIL cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 1

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-42-22-981Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-42-22-981Z\01-auth-login.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-42-22-981Z\02-chat-sse.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-42-22-981Z\03-tool-panel.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-42-22-981Z\04-code-as-action.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-42-22-981Z\failure.png`

## Suite Error

```
locator.waitFor: Error: strict mode violation: getByText(/Denied|User denied|Confirmation timed out/i) resolved to 3 elements:
    1) <p class="text-xs text-zinc-500">Denied / destructive</p> aka getByText('Denied / destructive')
    2) <pre class="mt-3 overflow-x-auto rounded-md px-3 py-2 text-xs bg-red-950/40 text-red-200">User denied this action.</pre> aka getByText('User denied this action.').first()
    3) <pre class="overflow-x-auto rounded-lg bg-zinc-950 px-3 py-3 text-xs text-zinc-300">User denied this action.</pre> aka getByRole('complementary').getByText('User denied this action.')

Call log:
[2m  - waiting for getByText(/Denied|User denied|Confirmation timed out/i) to be visible[22m

    at runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:271:72)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:340:21)
```

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31:8000/api/v1/conversations/247e37ec-554c-4450-a129-f17b4dd26bc4",
    "errorText": "net::ERR_ABORTED"
  }
]
```
