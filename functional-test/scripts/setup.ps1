$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDirectory = Split-Path -Parent $PSScriptRoot
$RepositoryDirectory = Split-Path -Parent $ProjectDirectory
$PackageDirectory = Join-Path $RepositoryDirectory "python"
$VirtualEnvironment = if ($env:RPD_TEST_VENV) {
    $env:RPD_TEST_VENV
} else {
    Join-Path $RepositoryDirectory ".venv-windows"
}
$VirtualEnvironmentPython = Join-Path $VirtualEnvironment "Scripts\python.exe"

if ($env:PYTHON) {
    $BasePython = $env:PYTHON
    $BasePythonArguments = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $BasePython = "py"
    $BasePythonArguments = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $BasePython = "python"
    $BasePythonArguments = @()
} else {
    throw "Python 3 was not found. Install Python 3.10 or newer and try again."
}

$Pyproject = Join-Path $PackageDirectory "pyproject.toml"
if (-not (Test-Path -LiteralPath $Pyproject -PathType Leaf)) {
    throw "Python package source is missing: $PackageDirectory"
}

$RepositoryVersionFile = Join-Path $RepositoryDirectory "VERSION"
$FunctionalTestVersionFile = Join-Path $ProjectDirectory "VERSION"
if (-not (Test-Path -LiteralPath $RepositoryVersionFile -PathType Leaf) -or
    -not (Test-Path -LiteralPath $FunctionalTestVersionFile -PathType Leaf)) {
    throw "Release version metadata is missing."
}
$RepositoryVersion = (Get-Content -Raw -LiteralPath $RepositoryVersionFile).Trim()
$FunctionalTestVersion = (Get-Content -Raw -LiteralPath $FunctionalTestVersionFile).Trim()
if ($RepositoryVersion -ne $FunctionalTestVersion) {
    throw "Functional-test version ($FunctionalTestVersion) does not match repository version ($RepositoryVersion)."
}

if (-not (Test-Path -LiteralPath $VirtualEnvironmentPython -PathType Leaf)) {
    & $BasePython @BasePythonArguments -m venv $VirtualEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not create the virtual environment: $VirtualEnvironment"
    }
}

& $VirtualEnvironmentPython -m pip install --disable-pip-version-check --upgrade --editable $PackageDirectory
if ($LASTEXITCODE -ne 0) {
    throw "The rp2350-remote-display package could not be installed."
}

$env:RPD_EXPECTED_VERSION = $RepositoryVersion
try {
    $VersionCheck = @'
import os
import rp2350_remote_display as rpd

expected = os.environ['RPD_EXPECTED_VERSION']
assert rpd.__version__ == expected, (rpd.__version__, expected)
print(f'Installed rp2350-remote-display {rpd.__version__} from this repository')
'@
    & $VirtualEnvironmentPython -c $VersionCheck
    if ($LASTEXITCODE -ne 0) {
        throw "The installed package version does not match this repository."
    }
} finally {
    Remove-Item Env:RPD_EXPECTED_VERSION -ErrorAction SilentlyContinue
}
