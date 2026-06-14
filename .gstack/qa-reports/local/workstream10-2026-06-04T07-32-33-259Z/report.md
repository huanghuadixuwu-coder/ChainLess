# Local Browser QA Report

- Run ID: `2026-06-04T07-32-33-259Z`
- Suite: `workstream10`
- URL: `http://118.196.142.31:3000`
- Final URL: `http://118.196.142.31:3000/login`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps


## Signals

- Console errors: 1
- Page errors: 0
- Request failures: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-32-33-259Z\report.json`

## Suite Error

```
page.waitForURL: Timeout 30000ms exceeded.
=========================== logs ===========================
waiting for navigation until "load"
============================================================
    at loginViaUi (E:\Chainless\scripts\windows-browser-qa.cjs:148:14)
    at async runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:185:17)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:308:21)
```

## Console Errors

```
Failed to load resource: the server responded with a status of 401 (Unauthorized)
```
