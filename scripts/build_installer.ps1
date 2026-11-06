param(
    [string]$Version
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $null
foreach ($candidate in $isccCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $iscc = $candidate
        break
    }
}
if (-not $iscc) {
    throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isinfo.php"
}

if (-not $Version) {
    $Version = & python -c "import sys; sys.path.insert(0, r'$root'); import version; print(version.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot read version."
    }
    $Version = $Version.Trim()
}

& $iscc "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed."
}
Write-Host "Done: dist\mpc-xpj-builder-v$Version-setup.exe"
