param(
    [Parameter(Mandatory = $true)]
    [string]$Url,

    [ValidateSet("chrome", "msedge")]
    [string]$Browser = "chrome",

    [switch]$Headless,
    [switch]$KeepOpen,

    [int]$TimeoutMs = 20000,

    [string]$WaitForTextGone = "Loading",

    [string]$ReportDir = ".gstack\\qa-reports\\local"
    ,
    [ValidateSet("smoke", "workstream10", "settings", "artifacts", "rich-input", "spec-complete")]
    [string]$Suite = "smoke",

    [string]$Tenant = "default",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [string]$ChatUsername = "",
    [string]$ChatPassword = "",
    [string]$ApiUrl = ""
)

$ErrorActionPreference = "Stop"

$NodeExe = "C:\Users\11367\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
$NodeModules = "C:\Users\11367\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
$ScriptPath = Join-Path $PSScriptRoot "windows-browser-qa.cjs"

if (-not (Test-Path $NodeExe)) {
    throw "Bundled Node runtime not found: $NodeExe"
}

if (-not (Test-Path $NodeModules)) {
    throw "Bundled Node modules not found: $NodeModules"
}

if (-not (Test-Path $ScriptPath)) {
    throw "QA script not found: $ScriptPath"
}

$env:NODE_PATH = $NodeModules

$ArgsList = @(
    $ScriptPath,
    "--url", $Url,
    "--browser", $Browser,
    "--timeout-ms", "$TimeoutMs",
    "--report-dir", $ReportDir,
    "--wait-for-text-gone", $WaitForTextGone,
    "--suite", $Suite
)

if (
    $PSBoundParameters.ContainsKey("Tenant") -or
    $PSBoundParameters.ContainsKey("Username") -or
    $PSBoundParameters.ContainsKey("Password")
) {
    $ArgsList += @(
        "--tenant", $Tenant,
        "--username", $Username,
        "--password", $Password
    )
}

if ($ApiUrl) {
    $ArgsList += @("--api-url", $ApiUrl)
}

if ($ChatUsername -and $ChatPassword) {
    $ArgsList += @(
        "--chat-username", $ChatUsername,
        "--chat-password", $ChatPassword
    )
}

if ($Headless) {
    $ArgsList += "--headless"
}
else {
    $ArgsList += "--headed"
}

if ($KeepOpen) {
    $ArgsList += "--keep-open"
}

Write-Host "Using bundled Node: $NodeExe"
Write-Host "Using bundled node_modules: $NodeModules"
Write-Host "Launching browser QA for: $Url"

& $NodeExe @ArgsList
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    throw "windows-browser-qa failed with exit code $exitCode"
}
