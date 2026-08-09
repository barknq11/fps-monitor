$root = 'C:\manus work\fps-monitor'
Set-Location $root
git rm --cached -q 'ship.ps1' 2>$null
Remove-Item "$root\ship.ps1" -Force -ErrorAction SilentlyContinue
git add -A
git commit -q -m "Ignore loose scratch scripts in the project root"
git push origin main 2>&1 | Select-Object -Last 2
Write-Output ''
Write-Output '--- tracked ps1 files (should only be tools/) ---'
git ls-files '*.ps1' | ForEach-Object { '  ' + $_ }
Write-Output ''
Write-Output '--- is the packaged app running? ---'
Get-CimInstance Win32_Process -Filter "Name='FPS Monitor.exe'" |
    Select-Object ProcessId, ExecutablePath | Format-List
$p = Get-Process 'FPS Monitor' -ErrorAction SilentlyContinue
if (-not $p) { Write-Output '  not running' }
Write-Output '--- is dist locked? ---'
try {
    $f = [System.IO.File]::Open("$root\dist\FPS Monitor\FPS Monitor.exe", 'Open', 'Write')
    $f.Close()
    Write-Output '  not locked - rebuild can proceed'
} catch {
    Write-Output '  LOCKED - the exe is in use, close it before rebuilding'
}
Remove-Item "$root\tools\cleanup_repo.ps1" -Force -ErrorAction SilentlyContinue
