# Local Browser QA Report

- Run ID: `2026-06-14T16-12-03-949Z`
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
- Ignored request failures: 1
- 429 responses: 0

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\rich-input-2026-06-14T16-12-03-949Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\rich-input-2026-06-14T16-12-03-949Z\failure.png`

## Suite Error

```
Error: virtual window did not reduce rendered rows: {"total":34,"rendered":34,"rows":34,"scrollHeight":3757,"clientHeight":3757}; page.waitForFunction: Timeout 15000ms exceeded.
    at E:\Chainless\scripts\qa\rich-input-suite.cjs:350:15
    at async runRichInput (E:\Chainless\scripts\qa\rich-input-suite.cjs:334:7)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:996:19)
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
