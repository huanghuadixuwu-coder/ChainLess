# Local Browser QA Report

- Run ID: `2026-06-14T10-53-27-130Z`
- Suite: `settings`
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
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\settings-2026-06-14T10-53-27-130Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\settings-2026-06-14T10-53-27-130Z\failure.png`

## Suite Error

```
page.waitForURL: Timeout 90000ms exceeded.
=========================== logs ===========================
waiting for navigation until "load"
============================================================
    at loginViaUi (E:\Chainless\scripts\windows-browser-qa.cjs:134:14)
    at async runSettings (E:\Chainless\scripts\windows-browser-qa.cjs:462:13)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:738:19)
```

## Console Errors

```
Failed to load resource: the server responded with a status of 401 (Unauthorized)
```
