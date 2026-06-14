# Local Browser QA Report

- Run ID: `2026-06-14T14-03-58-862Z`
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
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 0
- Ignored request failures: 0
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-03-58-862Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-03-58-862Z\failure.png`

## Suite Error

```
locator.waitFor: Timeout 90000ms exceeded.
Call log:
[2m  - waiting for getByText('file_write', { exact: true }) to be visible[22m

    at runArtifacts (E:\Chainless\scripts\windows-browser-qa.cjs:798:57)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:1225:19)
```
