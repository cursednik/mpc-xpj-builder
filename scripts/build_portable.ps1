param(
    [string]$Version
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"

if (-not $Version) {
    $Version = & python -c "import sys; sys.path.insert(0, r'$root'); import version; print(version.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot read version."
    }
    $Version = $Version.Trim()
}

$exeCli = Join-Path $dist "mpc-xpj-builder.exe"
$exeGui = Join-Path $dist "mpc-xpj-builder-gui.exe"
if (-not (Test-Path -LiteralPath $exeCli)) {
    throw "Missing $exeCli. Build EXEs first."
}
if (-not (Test-Path -LiteralPath $exeGui)) {
    throw "Missing $exeGui. Build GUI EXE first."
}

$stage = Join-Path $dist "portable-$Version"
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Path $stage | Out-Null

Copy-Item -LiteralPath $exeCli -Destination $stage
Copy-Item -LiteralPath $exeGui -Destination $stage
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination $stage
if (Test-Path -LiteralPath (Join-Path $root "docs\HARDWARE_TEST.md")) {
    Copy-Item -LiteralPath (Join-Path $root "docs\HARDWARE_TEST.md") -Destination $stage
}
$checks = @(
    (Join-Path $dist "mpc-xpj-builder.exe.sha256"),
    (Join-Path $dist "mpc-xpj-builder-gui.exe.sha256")
)
foreach ($check in $checks) {
    if (Test-Path -LiteralPath $check) {
        Copy-Item -LiteralPath $check -Destination $stage
    }
}

$zip = Join-Path $dist "mpc-xpj-builder-v$Version-win64.zip"
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -LiteralPath $stage -Recurse -Force
Write-Host "Done: $zip"
