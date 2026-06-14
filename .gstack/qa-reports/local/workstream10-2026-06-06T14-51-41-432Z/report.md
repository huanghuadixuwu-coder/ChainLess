# Local Browser QA Report

- Run ID: `2026-06-06T14-51-41-432Z`
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
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 1

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-51-41-432Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-51-41-432Z\01-auth-login.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-51-41-432Z\02-chat-sse.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-51-41-432Z\failure.png`

## Suite Error

```
locator.waitFor: Timeout 90000ms exceeded.
Call log:
[2m  - waiting for getByRole('complementary').getByText(/url/i) to be visible[22m

    at runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:243:8)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:331:19)
```

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31/api/v1/conversations/3500cf37-53b3-48bb-91e5-f7baf0ab7289",
    "errorText": "net::ERR_ABORTED"
  }
]
```
