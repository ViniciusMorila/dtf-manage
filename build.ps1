<#
.SYNOPSIS
  Builds the DTF Manager executable with PyInstaller and the Windows installer (Inno Setup 6).

.DESCRIPTION
  Output: dist\DTFManager\DTFManager.exe (one-folder build) and
  installer_output\DTFManager-Setup-<version>.exe (+ .sha256).
  The version comes from dtf_manager\core\version.py (single source, also used by installer.iss).
  After building, the frozen executable runs "--self-check" to prove that the
  SMBIOS reading (ctypes) and DPAPI work inside the packaged build.
  The release gate runs first; the installer is only generated after everything passed.

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

# Single source of the version: dtf_manager\core\version.py (APP_VERSION = "x.y.z").
$versionFile = Join-Path $PSScriptRoot "dtf_manager\core\version.py"
$versionMatch = Select-String -Path $versionFile -Pattern '^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"' | Select-Object -First 1
if (-not $versionMatch) { throw "APP_VERSION (x.y.z) not found in $versionFile" }
$appVersion = $versionMatch.Matches[0].Groups[1].Value
Write-Host "DTF Manager version: $appVersion"

function Find-InnoCompiler {
    $candidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

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

# Release gate (fails fast, before building): the packaged configuration must be real.
$gateFile = Join-Path ([System.IO.Path]::GetTempPath()) "dtf_release_gate.txt"
$env:PYTHONIOENCODING = "utf-8"
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python app.py --release-check 2> $gateFile
$gateExit = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($gateExit -ne 0) {
    Get-Content $gateFile -Encoding UTF8 | ForEach-Object { Write-Host "$_" -ForegroundColor Red }
    throw "Build abortado: corrija dtf_manager\data\app_config.json e dtf_manager\data\planos.json (veja as mensagens acima)."
}

$iscc = Find-InnoCompiler
if (-not $iscc) {
    throw ("Inno Setup 6 nao encontrado (ISCC.exe). Instale em https://jrsoftware.org/isdl.php " +
           "(Inno Setup 6.x) no caminho padrao: C:\Program Files (x86)\Inno Setup 6\ISCC.exe " +
           "(ou C:\Program Files\Inno Setup 6\, ou %LOCALAPPDATA%\Programs\Inno Setup 6\), " +
           "ou coloque a pasta do ISCC.exe no PATH.")
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
if ($process.ExitCode -ne 0) {
    $problems = (Get-Content $report -Raw | ConvertFrom-Json).release_problems
    foreach ($problem in $problems) { Write-Host "RELEASE BLOQUEADO: $problem" -ForegroundColor Red }
    throw "Self-check failed in the packaged build"
}

Write-Host "Build OK: $exe"

# Installer (only after the release gate, the build and the self-check passed).
$outputDir = Join-Path $PSScriptRoot "installer_output"
$setupName = "DTFManager-Setup-$appVersion.exe"
$setupPath = Join-Path $outputDir $setupName
if (Test-Path $setupPath) { Remove-Item -Force $setupPath }
& $iscc "/DAppVersion=$appVersion" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit code $LASTEXITCODE)" }
if (-not (Test-Path $setupPath)) { throw "Installer not found: $setupPath" }

$hash = (Get-FileHash -Algorithm SHA256 -Path $setupPath).Hash.ToLower()
$hashFile = Join-Path $outputDir "DTFManager-Setup-$appVersion.sha256"
[System.IO.File]::WriteAllText($hashFile, "$hash *$setupName`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Installer OK: $setupPath"
Write-Host "SHA-256: $hash"
Write-Host "Hash file: $hashFile"
