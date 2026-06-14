# Local Browser QA Report

- Run ID: `2026-06-14T14-43-26-195Z`
- Suite: `artifacts`
- URL: `http://localhost`
- Final URL: `http://localhost/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `true`

## Steps

- PASS auth-login
- PASS mock-provider-default
- PASS conversation-create
- PASS chat-file-write-tool
- PASS files-tab-real-artifact
- PASS diff-tab-real-unified-diff
- PASS reload-preserves-artifact-list
- PASS mock-provider-observed-tool-loop
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 0
- Ignored request failures: 1
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-43-26-195Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-43-26-195Z\01-files-artifact.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-43-26-195Z\02-diff-artifact.png`

## Ignored Request Failures

```json
[
  {
    "url": "http://localhost/chat?_rsc=yJVSf2-mUsVl2a-v",
    "errorText": "net::ERR_ABORTED"
  }
]
```
