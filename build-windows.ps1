param(
    [switch]$Backup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$basePython = (Get-Command 'python.exe' -ErrorAction Stop).Source
$basePythonVersion = & $basePython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine the active Python version: $basePython"
}

$venv = Join-Path $root '.venv-windows'
$python = Join-Path $venv 'Scripts/python.exe'
$buildId = Get-Date -Format 'yyyyMMddTHHmmss'
$buildRoot = Join-Path $root "build\windows-$buildId"
$distRoot = Join-Path $buildRoot 'dist'
$workRoot = Join-Path $buildRoot 'work'
$outputRoot = Join-Path $root 'dist\windows'
$outputExecutable = Join-Path $outputRoot 'EpicProfileSwitcher.exe'
$applicationIcon = Join-Path $root 'src\epic_profile_switcher\app.ico'

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

if (-not (Test-Path $python)) {
    Invoke-Checked $basePython @('-m', 'venv', $venv)
}

$venvPythonVersion = & $python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine the build environment Python version: $python"
}
if ($venvPythonVersion -ne $basePythonVersion) {
    throw "The existing build environment uses Python $venvPythonVersion, but Python $basePythonVersion is active. Remove '$venv' and run the build again."
}

if (-not (Test-Path $applicationIcon)) {
    throw "Application icon not found: $applicationIcon"
}

Invoke-Checked $python @('-c', 'import sys; raise SystemExit(sys.version_info < (3, 10))')
Invoke-Checked $python @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $python @('-m', 'pip', 'install', '-e', "${root}[dev,build]")
Invoke-Checked $python @('-m', 'pytest', '-q', (Join-Path $root 'tests'))

New-Item -ItemType Directory -Force -Path $distRoot, $workRoot | Out-Null
Invoke-Checked $python @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onefile',
    '--name', 'EpicProfileSwitcher',
    '--icon', $applicationIcon,
    '--add-data', "$applicationIcon;epic_profile_switcher",
    '--distpath', $distRoot,
    '--workpath', $workRoot,
    '--specpath', $workRoot,
    '--paths', (Join-Path $root 'src'),
    (Join-Path $root 'run_app.py')
)

$builtExecutable = Join-Path $distRoot 'EpicProfileSwitcher.exe'
if (-not (Test-Path $builtExecutable)) {
    throw 'PyInstaller did not create EpicProfileSwitcher.exe.'
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
if ($Backup -and (Test-Path $outputExecutable)) {
    $backupExecutable = Join-Path $outputRoot "EpicProfileSwitcher-$buildId.exe"
    Copy-Item $outputExecutable $backupExecutable
}
Copy-Item $builtExecutable $outputExecutable -Force
Write-Output "Windows executable built: $outputExecutable"