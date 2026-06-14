# Local Browser QA Report

- Run ID: `2026-06-06T15-17-11-199Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31`
- Final URL: `http://118.196.142.31/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `true`

## Steps

- PASS auth-login
- PASS conversation-create
- PASS conversation-rename
- PASS conversation-archive
- PASS chat-sse
- PASS tool-card-web-fetch
- PASS right-panel-files
- PASS code-as-action
- PASS destructive-confirmation-deny
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 1

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T15-17-11-199Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T15-17-11-199Z\01-auth-login.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T15-17-11-199Z\02-chat-sse.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T15-17-11-199Z\03-tool-panel.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T15-17-11-199Z\04-code-as-action.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T15-17-11-199Z\05-destructive-confirmation.png`

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31/api/v1/conversations/2f236d7c-3d41-4654-9812-3d96e952e9ce",
    "errorText": "net::ERR_ABORTED"
  }
]
```
