# Local Browser QA Report

- Run ID: `2026-06-04T07-41-24-357Z`
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

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-41-24-357Z\report.json`

## Suite Error

```
locator.waitFor: Error: strict mode violation: getByText(/url/i) resolved to 2 elements:
    1) <pre class="mt-3 overflow-x-auto rounded-md bg-zinc-950 px-3 py-2 text-xs text-zinc-400">{↵  "url": "https://example.com"↵}</pre> aka getByText('{ "url": "https://example.com').first()
    2) <pre class="overflow-x-auto rounded-lg bg-zinc-950 px-3 py-3 text-xs text-zinc-300">{↵  "url": "https://example.com"↵}</pre> aka getByRole('complementary').getByText('{ "url": "https://example.com')

Call log:
[2m  - waiting for getByText(/url/i) to be visible[22m

    at runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:251:34)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:333:21)
```

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31:8000/api/v1/conversations/9ae6527b-5ad7-4d2b-8697-7a132415fbc3",
    "errorText": "net::ERR_ABORTED"
  }
]
```
