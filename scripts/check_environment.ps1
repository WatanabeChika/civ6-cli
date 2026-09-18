[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 4318
)

$ErrorActionPreference = "SilentlyContinue"
Write-Output "civ6-cli environment check"

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    Write-Output "[OK] Python"
    & $python.Source --version
} else {
    Write-Output "[WARN] Python was not found on PATH"
}

$configRoots = @()
if ($env:USERPROFILE) {
    $configRoots += Join-Path $env:USERPROFILE "Documents\My Games\Sid Meier's Civilization VI"
}
if ($env:LOCALAPPDATA) {
    $configRoots += Join-Path $env:LOCALAPPDATA "Firaxis Games\Sid Meier's Civilization VI"
}

$options = $configRoots |
    Where-Object { Test-Path -LiteralPath $_ } |
    ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter AppOptions.txt -Recurse -File } |
    Select-Object -First 1

if ($options) {
    Write-Output "[OK] AppOptions.txt: $($options.FullName)"
    $setting = Select-String -LiteralPath $options.FullName -Pattern '^\s*EnableTuner\s+' |
        Select-Object -First 1
    if ($setting) {
        Write-Output "     $($setting.Line.Trim())"
    } else {
        Write-Output "[WARN] EnableTuner setting was not found"
    }
} else {
    Write-Output "[WARN] AppOptions.txt was not found"
}

$listener = Get-NetTCPConnection -State Listen -LocalAddress $HostAddress -LocalPort $Port `
    -ErrorAction SilentlyContinue -ErrorVariable ListenerError
if ($listener) {
    Write-Output "[OK] FireTuner is listening at $HostAddress`:$Port"
} elseif ($ListenerError) {
    Write-Output "[WARN] The FireTuner listener could not be inspected in this shell"
} else {
    Write-Output "[WARN] No listener at $HostAddress`:$Port"
    Write-Output "       Enable Tuner, enter a single-player map, and close other FireTuner clients."
}

Write-Output "This check is read-only and does not modify game settings or saves."
Write-Output "Enabling Tuner commonly disables Steam achievements for the save."
