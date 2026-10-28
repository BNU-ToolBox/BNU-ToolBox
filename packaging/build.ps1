param(
    [string]$PythonLauncher = "py -3.13",
    [string]$PythonVersion = "3.13.9"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BuildDir = Join-Path $Root "build"
$CacheDir = Join-Path $BuildDir "cache"
$StageDir = Join-Path $BuildDir "stage"
$OutputDir = Join-Path $Root "dist\installer"
$RuntimeDir = Join-Path $StageDir "runtime"
$SitePackages = Join-Path $RuntimeDir "Lib\site-packages"

function Assert-PathUnderRoot([string]$Path) {
    $ResolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $ResolvedPath = [IO.Path]::GetFullPath($Path)
    if (-not $ResolvedPath.StartsWith(
            $ResolvedRoot + "\",
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside repository: $ResolvedPath"
    }
}

function Remove-BuildPath([string]$Path) {
    Assert-PathUnderRoot $Path
    if (Test-Path -LiteralPath $Path) {
        Get-ChildItem -LiteralPath $Path -Recurse -Force -File |
            ForEach-Object { $_.IsReadOnly = $false }
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Find-InnoSetup {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $Root "tools\InnoSetup\ISCC.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    throw "Inno Setup 6 was not found. Install JRSoftware.InnoSetup."
}

New-Item -ItemType Directory -Force -Path $CacheDir, $StageDir, $OutputDir |
    Out-Null

Remove-BuildPath $StageDir
New-Item -ItemType Directory -Force -Path `
    $StageDir, $RuntimeDir, $SitePackages | Out-Null

$EmbedZip = Join-Path $CacheDir "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path -LiteralPath $EmbedZip)) {
    $Url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $EmbedZip
}
Expand-Archive -LiteralPath $EmbedZip -DestinationPath $RuntimeDir -Force

$PthFile = Get-ChildItem -LiteralPath $RuntimeDir -Filter "python*._pth" |
    Select-Object -First 1
if (-not $PthFile) {
    throw "Embedded Python _pth file was not found"
}
$PthLines = Get-Content -LiteralPath $PthFile.FullName
if ($PthLines -notcontains "Lib\site-packages") {
    Add-Content -LiteralPath $PthFile.FullName -Value "Lib\site-packages"
}

$PythonExe = (& cmd /c "$PythonLauncher -c `"import sys;print(sys.executable)`"").Trim()
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python launcher did not resolve to an executable: $PythonLauncher"
}

& $PythonExe -m pip install `
    --disable-pip-version-check `
    --no-compile `
    --upgrade `
    --target $SitePackages `
    -r (Join-Path $Root "requirements.lock")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed"
}

Copy-Item -LiteralPath (Join-Path $Root "app") `
    -Destination (Join-Path $StageDir "app") -Recurse
Copy-Item -LiteralPath (Join-Path $Root "plugins") `
    -Destination (Join-Path $StageDir "plugins") -Recurse
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination $StageDir
Copy-Item -LiteralPath (Join-Path $Root "THIRD_PARTY_NOTICES.md") `
    -Destination $StageDir
Copy-Item -LiteralPath (Join-Path $Root "start.bat") -Destination $StageDir

$PythonLicense = Join-Path $RuntimeDir "LICENSE.txt"
if (Test-Path -LiteralPath $PythonLicense) {
    Copy-Item -LiteralPath $PythonLicense `
        -Destination (Join-Path $RuntimeDir "PYTHON_LICENSE.txt") -Force
}

Get-ChildItem -LiteralPath $StageDir -Recurse -Directory -Force |
    Where-Object {
        $_.Name -in @("__pycache__", "data", ".pytest_cache", ".ruff_cache")
    } |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $StageDir -Recurse -File |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    Remove-Item -Force

$TestCommand = @"
import fastapi, uvicorn, selenium, cryptography, requests, multipart
print('runtime dependencies ok')
"@
& (Join-Path $RuntimeDir "python.exe") -c $TestCommand
if ($LASTEXITCODE -ne 0) {
    throw "Bundled runtime smoke test failed"
}
Get-ChildItem -LiteralPath $StageDir -Recurse -Directory -Force |
    Where-Object {
        $_.Name -in @("__pycache__", "data", ".pytest_cache", ".ruff_cache")
    } |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $StageDir -Recurse -File |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    Remove-Item -Force

$VersionLine = Get-Content -LiteralPath (Join-Path $Root "app\version.py") |
    Select-String -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $VersionLine) {
    throw "Application version was not found"
}
$AppVersion = $VersionLine.Matches[0].Groups[1].Value

$Iscc = Find-InnoSetup
& $Iscc `
    "/DAppVersion=$AppVersion" `
    "/DStageDir=$StageDir" `
    "/DOutputDir=$OutputDir" `
    (Join-Path $PSScriptRoot "BNU-ToolBox.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed"
}

$Installer = Join-Path $OutputDir "BNU-ToolBox-Setup-$AppVersion.exe"
if (-not (Test-Path -LiteralPath $Installer)) {
    throw "Installer was not produced: $Installer"
}
$InstallerHash = Get-FileHash -Algorithm SHA256 -LiteralPath $Installer
$ChecksumFile = Join-Path $OutputDir "SHA256SUMS.txt"
"$($InstallerHash.Hash)  $([IO.Path]::GetFileName($Installer))" |
    Set-Content -LiteralPath $ChecksumFile -Encoding ascii
$InstallerHash | Format-List
Write-Host "Installer: $Installer"
Write-Host "Checksum:  $ChecksumFile"
