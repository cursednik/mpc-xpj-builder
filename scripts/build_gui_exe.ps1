param(
    [string]$Name = "mpc-xpj-builder-gui",
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
    "--windowed",
    "--name", $Name,
    "--noconfirm"
)
if ($Clean) {
    $arguments += "--clean"
}
$arguments += "gui.py"

python -m PyInstaller @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host "Done: dist\$Name.exe"
