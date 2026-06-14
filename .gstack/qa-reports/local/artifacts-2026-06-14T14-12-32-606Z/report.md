# Local Browser QA Report

- Run ID: `2026-06-14T14-12-32-606Z`
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
- Ignored request failures: 1
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-12-32-606Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T14-12-32-606Z\failure.png`

## Suite Error

```
locator.waitFor: Error: strict mode violation: getByTestId('artifact-file-list').getByText('w6/w6-artifacts-1781446352858.py') resolved to 2 elements:
    1) <p class="truncate text-xs font-medium">w6/w6-artifacts-1781446352858.py</p> aka getByTestId('artifact-row')
    2) <p class="truncate text-xs font-medium text-zinc-200">w6/w6-artifacts-1781446352858.py</p> aka getByText('w6/w6-artifacts-1781446352858').nth(4)

Call log:
[2m  - waiting for getByTestId('artifact-file-list').getByText('w6/w6-artifacts-1781446352858.py') to be visible[22m

    at runArtifacts (E:\Chainless\scripts\windows-browser-qa.cjs:806:62)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:1229:19)
```

## Ignored Request Failures

```json
[
  {
    "url": "http://localhost/chat?_rsc=yJVSf2-mUsVl2a-v",
    "errorText": "net::ERR_ABORTED"
  }
]
```
