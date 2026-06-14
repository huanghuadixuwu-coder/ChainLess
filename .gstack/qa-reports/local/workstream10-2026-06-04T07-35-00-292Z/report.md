# Local Browser QA Report

- Run ID: `2026-06-04T07-35-00-292Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31:3000`
- Final URL: `http://118.196.142.31:3000/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps


## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 1

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-35-00-292Z\report.json`

## Suite Error

```
locator.waitFor: Timeout 60000ms exceeded.
Call log:
[2m  - waiting for getByText(/WS10 chat SSE/i) to be visible[22m

    at runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:239:42)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:328:21)
```

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31:8000/api/v1/conversations/6df3780c-3ba2-4533-be8a-17aae16c26c3",
    "errorText": "net::ERR_ABORTED"
  }
]
```
