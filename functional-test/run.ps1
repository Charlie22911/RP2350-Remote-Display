$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDirectory = $PSScriptRoot
$RepositoryDirectory = Split-Path -Parent $ProjectDirectory
$VirtualEnvironment = if ($env:RPD_TEST_VENV) {
    $env:RPD_TEST_VENV
} else {
    Join-Path $RepositoryDirectory ".venv-windows"
}
$VirtualEnvironmentPython = Join-Path $VirtualEnvironment "Scripts\python.exe"

& (Join-Path $ProjectDirectory "scripts\setup.ps1")
& $VirtualEnvironmentPython (Join-Path $ProjectDirectory "functional_test.py") @args
exit $LASTEXITCODE
