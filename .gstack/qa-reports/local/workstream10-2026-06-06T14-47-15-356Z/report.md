# Local Browser QA Report

- Run ID: `2026-06-06T14-47-15-356Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31`
- Final URL: `http://118.196.142.31/login`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps


## Signals

- Console errors: 1
- Page errors: 0
- Request failures: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-47-15-356Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-06T14-47-15-356Z\failure.png`

## Suite Error

```
page.waitForURL: Timeout 60000ms exceeded.
=========================== logs ===========================
waiting for navigation until "load"
============================================================
    at loginViaUi (E:\Chainless\scripts\windows-browser-qa.cjs:124:14)
    at async runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:163:13)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:298:19)
```

## Console Errors

```
Failed to load resource: the server responded with a status of 401 (Unauthorized)
```
