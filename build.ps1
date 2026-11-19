<#
.SYNOPSIS
  Builds the DTF Manager executable with PyInstaller (no installer is generated).

.DESCRIPTION
  Output: dist\DTFManager\DTFManager.exe (one-folder build).
  After building, the frozen executable runs "--self-check" to prove that the
  SMBIOS reading (ctypes) and DPAPI work inside the packaged build.

.EXAMPLE
  .\build.ps1                  # build and self-check
  .\build.ps1 -InstallDeps     # also installs requirements.txt first
  .\build.ps1 -Clean           # remove previous build output first
  .\build.ps1 -RunTests        # run the unit tests (one process per module) before building
#>
param(
    [string]$Python = "python",
    [switch]$InstallDeps,
    [switch]$Clean,
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($InstallDeps) {
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

if ($Clean) {
    foreach ($path in @("build\_work", "dist\DTFManager")) {
        if (Test-Path $path) { Remove-Item -Recurse -Force $path }
    }
}

if ($RunTests) {
    $env:QT_QPA_PLATFORM = "offscreen"
    # One process per module: several Qt windows in a single process are not stable.
    foreach ($file in Get-ChildItem tests -Filter "test_*.py") {
        & $Python -m unittest "tests.$($file.BaseName)"
        if ($LASTEXITCODE -ne 0) { throw "Tests failed: $($file.BaseName)" }
    }
    Remove-Item Env:QT_QPA_PLATFORM
}

& $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\_work build\dtf_manager.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $PSScriptRoot "dist\DTFManager\DTFManager.exe"
if (-not (Test-Path $exe)) { throw "Executable not found: $exe" }

# Self-check inside the frozen build (no window, no network).
$report = Join-Path ([System.IO.Path]::GetTempPath()) "dtf_manager_self_check.json"
if (Test-Path $report) { Remove-Item $report }
$process = Start-Process -FilePath $exe -ArgumentList "--self-check", "`"$report`"" -Wait -PassThru
if (-not (Test-Path $report)) { throw "Self-check produced no report (exit code $($process.ExitCode))" }
Get-Content $report
if ($process.ExitCode -ne 0) { throw "Self-check failed in the packaged build" }

Write-Host "Build OK: $exe"
