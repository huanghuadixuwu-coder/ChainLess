# Local Browser QA Report

- Run ID: `2026-06-14T13-59-50-184Z`
- Suite: `artifacts`
- URL: `http://localhost`
- Final URL: `http://localhost/login`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps


## Signals

- Console errors: 1
- Page errors: 0
- Request failures: 0
- Ignored request failures: 0
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T13-59-50-184Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\artifacts-2026-06-14T13-59-50-184Z\failure.png`

## Suite Error

```
page.waitForURL: Timeout 90000ms exceeded.
=========================== logs ===========================
waiting for navigation until "load"
============================================================
    at loginViaUi (E:\Chainless\scripts\windows-browser-qa.cjs:384:14)
    at async runArtifacts (E:\Chainless\scripts\windows-browser-qa.cjs:728:13)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:1197:19)
```

## Console Errors

```
Failed to load resource: the server responded with a status of 401 (Unauthorized)
```
