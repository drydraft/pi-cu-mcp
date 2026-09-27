param(
    [string]$AllowedApps = '*',
    [switch]$InstallGlobalSkill
)
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configDirectory = Join-Path $env:USERPROFILE '.config\mcp'
$configPath = Join-Path $configDirectory 'mcp.json'
$skillSource = Join-Path $projectRoot 'skills\pi-windows-mcp'
$skillTarget = Join-Path $env:USERPROFILE '.pi\agent\skills\pi-windows-mcp'

New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null

if (Test-Path -LiteralPath $configPath) {
    $rawConfig = Get-Content -Raw -LiteralPath $configPath
    if ([string]::IsNullOrWhiteSpace($rawConfig)) {
        $config = [pscustomobject]@{}
    }
    else {
        $config = $rawConfig | ConvertFrom-Json
    }
}
else {
    $config = [pscustomobject]@{}
}

if (-not $config.PSObject.Properties['mcpServers']) {
    $config | Add-Member -MemberType NoteProperty -Name 'mcpServers' -Value ([pscustomobject]@{})
}
elseif ($null -eq $config.mcpServers) {
    $config.mcpServers = [pscustomobject]@{}
}

$entry = [pscustomobject]@{
    command = 'powershell.exe'
    args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $projectRoot 'start.ps1'))
    env = [pscustomobject]@{ WINDOWS_MCP_ALLOWED_APPS = $AllowedApps }
    directTools = $true
}
$config.mcpServers | Add-Member -MemberType NoteProperty -Name 'windows-desktop' -Value $entry -Force
$json = $config | ConvertTo-Json -Depth 10
$utf8NoBom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
[System.IO.File]::WriteAllText($configPath, $json, $utf8NoBom)

Write-Host "Configured windows-desktop in $configPath"
if ($InstallGlobalSkill) {
    New-Item -ItemType Directory -Path $skillTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $skillSource '*') -Destination $skillTarget -Recurse -Force
    Write-Host "Installed the pi-windows-mcp Skill in $skillTarget"
}
else {
    Write-Host 'The Pi package supplies the pi-windows-mcp Skill; no duplicate global copy was created.'
}
if (-not (Get-Command pi -ErrorAction SilentlyContinue)) {
    Write-Warning 'Pi was not found on PATH. Install Pi and run: pi install npm:pi-mcp-adapter'
}
else {
    Write-Host 'Pi was found. Run /reload in Pi after the adapter is installed.'
}
