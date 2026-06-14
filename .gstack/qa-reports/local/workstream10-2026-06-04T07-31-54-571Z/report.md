# Local Browser QA Report

- Run ID: `2026-06-04T07-31-54-571Z`
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
- Request failures: 2

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\workstream10-2026-06-04T07-31-54-571Z\report.json`

## Suite Error

```
locator.click: Error: strict mode violation: getByRole('button', { name: 'New Chat' }) resolved to 2 elements:
    1) <button type="button" data-slot="button" class="group/button inline-flex shrink-0 items-center justify-center rounded-lg bg-clip-padding text-sm font-medium whitespace-nowrap transition-all outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 d…>…</button> aka getByRole('button', { name: 'New Chat' }).first()
    2) <button class="min-w-0 flex-1 px-3 py-2 text-left">…</button> aka getByRole('button', { name: 'New Chat' }).nth(1)

Call log:
[2m  - waiting for getByRole('button', { name: 'New Chat' })[22m

    at runWorkstream10 (E:\Chainless\scripts\windows-browser-qa.cjs:190:56)
    at async main (E:\Chainless\scripts\windows-browser-qa.cjs:307:21)
```

## Request Failures

```json
[
  {
    "url": "http://118.196.142.31:3000/_next/static/chunks/3r-o7j8njn_0w.js",
    "errorText": "net::ERR_ABORTED"
  },
  {
    "url": "http://118.196.142.31:3000/_next/static/chunks/2gxqyq1f2nu76.js",
    "errorText": "net::ERR_ABORTED"
  }
]
```
