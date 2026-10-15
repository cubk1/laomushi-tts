@echo off
rem ============================================================
rem  Pick the GPT-SoVITS folder once, save it to config.local.txt
rem  (called automatically by run_gui.bat on first start)
rem ============================================================
setlocal
set "TARGET=%~dp0config.local.txt"
echo Select the GPT-SoVITS folder in the dialog window...
powershell -NoProfile -STA -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'Select the GPT-SoVITS folder (contains runtime and GPT_SoVITS)'; $d.ShowNewFolderButton = $false; if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $p = $d.SelectedPath; if ((Test-Path (Join-Path $p 'GPT_SoVITS')) -or (Test-Path (Join-Path $p 'runtime\python.exe'))) { [System.IO.File]::WriteAllText('%TARGET%', $p + [Environment]::NewLine, [System.Text.Encoding]::Default); Write-Host ('[OK] saved: ' + $p) } else { Write-Host '[ERROR] that folder has no GPT_SoVITS or runtime' } } else { Write-Host '[CANCEL] nothing changed' }"
echo.
pause
