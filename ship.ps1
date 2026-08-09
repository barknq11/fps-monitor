$root = 'C:\manus work\fps-monitor'
Set-Location $root

Write-Output '=== rebuild ==='
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\tools\build.ps1" 2>&1 |
    Select-Object -Last 10

Write-Output ''
Write-Output '=== are the new glyphs inside the bundle? ==='
$app = "$root\dist\FPS Monitor\_internal\assets\ui"
if (Test-Path $app) {
    Get-ChildItem $app | ForEach-Object { '  ok  ' + $_.Name }
} else {
    Write-Output '  MISSING: assets\ui not bundled'
}

Write-Output ''
Write-Output '=== commit + push ==='
git add -A
git status --short
git commit -q -m "Make dropdowns visually distinct from number fields

Overriding QComboBox::drop-down removed the native chevron, so a dropdown
looked identical to a text or number input. Adds generated arrow glyphs per
theme: combos get a divider and a chevron, spin boxes get stepper arrows."
git --no-pager log --oneline -1
git push origin main 2>&1 | Select-Object -Last 3
$local = (git rev-parse HEAD).Trim()
$sha = ((git ls-remote origin refs/heads/main) -split "\s+")[0]
Write-Output ''
if ($local -eq $sha) { Write-Output "IN SYNC ($($local.Substring(0,7)))" } else { Write-Output 'OUT OF SYNC' }
Write-Output ''
Get-Content "$root\dist\FPS-Monitor-v1.0.0-win64.zip.sha256"
Remove-Item "$root\ship.ps1" -Force -ErrorAction SilentlyContinue
