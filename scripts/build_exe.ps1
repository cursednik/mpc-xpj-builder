param(
    [string]$Name = "mpc-xpj-builder",
    [switch]$Clean
)

$ErrorActionPreference = "Continue"
python -c "import PyInstaller" 2>$null
$hasPyInstaller = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"

if (-not $hasPyInstaller) {
    throw "PyInstaller is not installed. Run: python -m pip install -e .[dev]"
}

$arguments = @(
    "--onefile",
    "--name", $Name,
    "--noconfirm"
)
if ($Clean) {
    $arguments += "--clean"
}
$arguments += "main.py"

python -m PyInstaller @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host "Done: dist\$Name.exe"
