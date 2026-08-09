# Builds the distributable folder and zips it for a GitHub Release.
#   powershell -ExecutionPolicy Bypass -File tools\build.ps1
#   powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Version v1.0.1
param([string]$Version = 'v1.0.0')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Output '=== cleaning ==='
Remove-Item "$root\build", "$root\dist" -Recurse -Force -ErrorAction SilentlyContinue

if (-not (Test-Path "$root\assets\icon.ico")) {
    Write-Output 'assets\icon.ico missing - generating from the logo'
    python tools\make_icon.py
}

Write-Output '=== building (this takes a minute) ==='
python -m PyInstaller --noconfirm --clean FPSMonitor.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$app = "$root\dist\FPS Monitor"
if (-not (Test-Path "$app\FPS Monitor.exe")) { throw 'exe not produced' }

Write-Output '=== bundled resources present? ==='
foreach ($p in @(
    '_internal\vendor\PresentMon.exe',
    '_internal\vendor\LibreHardwareMonitorLib.dll',
    '_internal\vendor\HidSharp.dll',
    '_internal\assets\icon.ico',
    '_internal\pythonnet\runtime\Python.Runtime.dll'
)) {
    $full = Join-Path $app $p
    if (Test-Path $full) { Write-Output ("  ok       " + $p) }
    else { Write-Output ("  MISSING  " + $p) }
}

$size = (Get-ChildItem $app -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
$count = (Get-ChildItem $app -Recurse -File | Measure-Object).Count
Write-Output ('=== built: {0:N0} files, {1:N1} MB ===' -f $count, $size)

$zip = "$root\dist\FPS-Monitor-$Version-win64.zip"
Write-Output "=== zipping to $zip ==="
Compress-Archive -Path $app -DestinationPath $zip -Force
$zipMb = (Get-Item $zip).Length / 1MB
Write-Output ('  {0:N1} MB' -f $zipMb)

Write-Output '=== SHA-256 (publish this next to the download) ==='
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
Write-Output "  $hash"
Set-Content -Path "$zip.sha256" -Value "$hash  $(Split-Path $zip -Leaf)"
Write-Output ''
Write-Output 'Done. Test dist\FPS Monitor\FPS Monitor.exe before publishing.'
