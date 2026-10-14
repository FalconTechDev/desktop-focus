$dir = Join-Path $env:LOCALAPPDATA 'Programs\DesktopFocus'
$exe = Join-Path $dir 'DesktopFocus.exe'
$shell = New-Object -ComObject WScript.Shell

if ($MyInvocation.MyCommand.Path) {
    $ans = $shell.Popup("Удалить Desktop Focus?", 0, 'Desktop Focus', 36)
    if ($ans -ne 6) { exit 0 }
}

Get-Process DesktopFocus -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

$state = Join-Path $env:USERPROFILE '.desktop_focus_stash\state.json'
if ((Test-Path $exe) -and (Test-Path $state)) {
    $hidden = $false
    try { $hidden = (Get-Content $state -Raw -Encoding UTF8 | ConvertFrom-Json).hidden.Count -gt 0 } catch {}
    if ($hidden) {
        # вернуть скрытые иконки на места перед удалением
        Start-Process $exe -ArgumentList '--restore' -Verb RunAs -Wait
    }
}

Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Desktop Focus.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DesktopFocus' -Recurse -Force -ErrorAction SilentlyContinue
$stash = Join-Path $env:USERPROFILE '.desktop_focus_stash'
if ((Test-Path $stash) -and -not (Get-ChildItem $stash -Recurse -File -Exclude state.json -ErrorAction SilentlyContinue)) {
    Remove-Item $stash -Recurse -Force -ErrorAction SilentlyContinue
}

Start-Process cmd.exe -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$dir`"" -WindowStyle Hidden
$null = $shell.Popup("Desktop Focus удалён.", 0, 'Desktop Focus', 64)
