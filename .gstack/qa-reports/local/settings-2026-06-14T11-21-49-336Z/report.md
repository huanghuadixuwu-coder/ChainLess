# Local Browser QA Report

- Run ID: `2026-06-14T11-21-49-336Z`
- Suite: `settings`
- URL: `http://localhost`
- Final URL: `http://localhost/chat`
- Browser: `chrome`
- Mode: `headless`
- OK: `false`

## Steps

- PASS auth-login-admin
- PASS settings-route-open
- PASS settings-section-provider
- PASS settings-section-agent
- PASS settings-section-tools
- PASS settings-section-memories
- PASS settings-section-channel
- PASS settings-section-proactive
- PASS settings-section-skills
- PASS settings-section-eval
- PASS settings-section-system
- PASS provider-create-mask-default
- PASS agent-create-active
- PASS tool-risk-override-reset
- PASS mcp-register-test
- PASS memory-create-search-merge
- PASS channel-feishu-secret-surface
- PASS proactive-create-runs-visible
- PASS skill-create-match
- PASS eval-dry-run
- PASS theme-toggle-default-dark-persist
- PASS auth-login-chat-admin
- PASS chat-context-banner-provider-switch
- PASS cleanup-settings-artifacts

## Signals

- Console errors: 1
- Page errors: 0
- Request failures: 2
- 429 responses: 1

## Artifacts

- JSON report: `E:\Chainless\.gstack\qa-reports\local\settings-2026-06-14T11-21-49-336Z\report.json`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\settings-2026-06-14T11-21-49-336Z\01-settings-sections.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\settings-2026-06-14T11-21-49-336Z\02-settings-system-theme.png`
- Screenshot: `E:\Chainless\.gstack\qa-reports\local\settings-2026-06-14T11-21-49-336Z\03-chat-context-banner.png`

## Console Errors

```
Failed to load resource: the server responded with a status of 429 (Too Many Requests)
```

## Request Failures

```json
[
  {
    "url": "http://localhost/chat?_rsc=yJVSf2-mUsVl2a-v",
    "errorText": "net::ERR_ABORTED"
  },
  {
    "url": "http://localhost/chat?_rsc=yJVSf2-mUsVl2a-v",
    "errorText": "net::ERR_ABORTED"
  }
]
```

## 429 Responses

```json
[
  "http://localhost/api/v1/skills/?limit=100"
]
```
