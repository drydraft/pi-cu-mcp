$ErrorActionPreference = 'Stop'
$platform = [System.Environment]::OSVersion.Platform
if ($platform -ne [System.PlatformID]::Win32NT) {
    throw 'Pi CU MCP requires Windows 10 or Windows 11.'
}
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$environmentPath = Join-Path $projectRoot '.venv'
$pythonPath = Join-Path $environmentPath 'Scripts\python.exe'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install uv and rerun install.ps1.'
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    $basePython = (& uv python find 3.12).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $basePython) {
        throw 'Python 3.12 was not found by uv.'
    }
    & $basePython -m venv $environmentPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
}

& uv pip install --python $pythonPath --requirement (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install MCP dependencies.' }
Write-Host 'Windows MCP dependencies installed.'
