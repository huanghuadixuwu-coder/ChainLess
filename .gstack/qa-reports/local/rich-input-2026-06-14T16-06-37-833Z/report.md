# Local Browser QA Report

- Run ID: `2026-06-14T16-06-37-833Z`
- Suite: `rich-input`
- URL: `http://localhost`
- Final URL: `http://localhost/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps

- PASS auth-login
- PASS mock-provider-default
- PASS ctrl-n-ignored-inside-input
- PASS ctrl-n-new-conversation
- PASS ctrl-k-ignored-inside-input
- PASS ctrl-k-command-palette
- PASS command-palette-new-conversation
- PASS at-tool-picker-keyboard-selection
- PASS file-picker-upload
- PASS drag-drop-upload
- PASS chat-with-attachments
- PASS backend-injected-upload-content
- PASS markdown-code-fold
- PASS markdown-code-copy
- PASS cleanup-conversations

## Signals

- Console errors: 0
- Page errors: 0
- Request failures: 0
- Ignored request failures: 0
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\rich-input-2026-06-14T16-06-37-833Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\rich-input-2026-06-14T16-06-37-833Z\failure.png`

## Suite Error

```
page.waitForFunction: Timeout 120000ms exceeded.
    at runRichInput (E:\Chainless\scripts\qa\rich-input-suite.cjs:334:18)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:996:19)
```
