$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$LogPath = Join-Path $Root "build-windows.log"
$TranscriptStarted = $false
$BuildSucceeded = $false

function Invoke-Python {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    Write-Host "`n> Python $($Arguments -join ' ')"
    & $script:PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: python $($Arguments -join ' ')"
    }
}

try {
    if (Test-Path $LogPath) {
        Remove-Item $LogPath -Force
    }
    Start-Transcript -Path $LogPath -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host "task runner Windows build"
    Write-Host "Project folder: $Root"
    Write-Host "Build log: $LogPath"

    $ProjectFile = Join-Path $Root "pyproject.toml"
    $SpecFile = Join-Path $Root "packaging\task-runner.spec"
    if (-not (Test-Path -LiteralPath $ProjectFile -PathType Leaf)) {
        throw "pyproject.toml was not found in the project folder '$Root'. Extract the complete task-runner folder and run packaging\build-windows.bat from there."
    }
    if (-not (Test-Path -LiteralPath $SpecFile -PathType Leaf)) {
        throw "The PyInstaller spec was not found at '$SpecFile'. Extract the complete task-runner folder before building."
    }

    if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
        throw "The Python launcher ('py') was not found. Install 64-bit Python 3.13 and enable the Python launcher."
    }

    $version = & py -3.13 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or "$version".Trim() -ne "3.13") {
        throw "Python 3.13 was not found. Install 64-bit Python 3.13 from python.org and run this script again."
    }
    $bits = & py -3.13 -c "import struct; print(struct.calcsize('P') * 8)"
    if ($LASTEXITCODE -ne 0 -or "$bits".Trim() -ne "64") {
        throw "The build requires 64-bit Python 3.13."
    }

    $VenvPath = Join-Path $Root ".venv-build"
    $PythonPath = Join-Path $VenvPath "Scripts\python.exe"
    if (Test-Path $PythonPath) {
        $existingVersion = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        $existingBits = & $PythonPath -c "import struct; print(struct.calcsize('P') * 8)"
        if ($LASTEXITCODE -ne 0 -or "$existingVersion".Trim() -ne "3.13" -or "$existingBits".Trim() -ne "64") {
            Write-Host "The existing build environment is not Python 3.13 x64; recreating it."
            Remove-Item $VenvPath -Recurse -Force
        }
    }

    if (-not (Test-Path $PythonPath)) {
        Write-Host "`n> Creating isolated build environment"
        & py -3.13 -m venv .venv-build
        if ($LASTEXITCODE -ne 0) { throw "Could not create .venv-build (exit code $LASTEXITCODE)." }
    }

    Invoke-Python @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Python @("-m", "pip", "install", "-e", ".[dev,documents,ocr,build]")
    Invoke-Python @("-m", "pytest", "-q")
    Invoke-Python @("packaging\prepare_icon.py")

    $DistPath = Join-Path $Root "dist"
    $AppPath = Join-Path $DistPath "task-runner"
    $ZipPath = Join-Path $DistPath "task-runner-windows-x64.zip"
    if (Test-Path $AppPath) { Remove-Item $AppPath -Recurse -Force }
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

    Invoke-Python @("-m", "PyInstaller", "--noconfirm", "--clean", "packaging\task-runner.spec")

    $ExePath = Join-Path $AppPath "task-runner.exe"
    if (-not (Test-Path $ExePath)) {
        throw "PyInstaller returned success but task-runner.exe was not found at $ExePath."
    }

    Copy-Item (Join-Path $Root "packaging\README-WINDOWS.txt") (Join-Path $AppPath "README.txt") -Force
    Copy-Item (Join-Path $Root "LICENSE") (Join-Path $AppPath "LICENSE") -Force
    Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.txt") (Join-Path $AppPath "THIRD_PARTY_NOTICES.txt") -Force
    Compress-Archive -Path $AppPath -DestinationPath $ZipPath -CompressionLevel Optimal -Force

    if (-not (Test-Path $ZipPath) -or (Get-Item $ZipPath).Length -le 0) {
        throw "The release ZIP was not created or is empty."
    }

    Write-Host "`nBUILD SUCCEEDED"
    Write-Host "App folder: $AppPath"
    Write-Host "Executable: $ExePath"
    Write-Host "Release ZIP: $ZipPath"
    Write-Host "This local build is unsigned. Use the approved CI signing process for a signed public release."
    $BuildSucceeded = $true
}
catch {
    Write-Host "`nBUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Read the full output in: $LogPath"
}
finally {
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if (-not $BuildSucceeded) {
    exit 1
}
exit 0
