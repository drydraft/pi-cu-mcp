$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    [Console]::Error.WriteLine('Windows MCP is not installed. Run install.ps1 first.')
    exit 1
}
Push-Location $projectRoot
try {
    & $pythonPath -m windows_mcp
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $exitCode
