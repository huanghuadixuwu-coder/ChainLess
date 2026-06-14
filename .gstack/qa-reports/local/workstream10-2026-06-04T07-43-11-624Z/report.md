# Local Browser QA Report

- Run ID: `2026-06-04T07-43-11-624Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31:3000`
- Final URL: `http://118.196.142.31:3000/chat`
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

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-43-11-624Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-43-11-624Z\01-auth-login.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-43-11-624Z\02-chat-sse.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-43-11-624Z\03-tool-panel.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-43-11-624Z\04-code-as-action.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-43-11-624Z\05-destructive-confirmation.png`

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31:8000/api/v1/conversations/2112bfb3-6fb8-4c7c-9311-f54b5be6692e",
    "errorText": "net::ERR_ABORTED"
  }
]
```
