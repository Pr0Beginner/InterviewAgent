param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$VenvDirectory = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDirectory "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$EnvTemplate = Join-Path $ProjectRoot "backend\.env.example"
$EnvFile = Join-Path $ProjectRoot "backend\.env"

function Invoke-Checked {
    param(
        [string]$Description,
        [string]$Executable,
        [string[]]$Arguments
    )

    Write-Host "[INFO] $Description"
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Find-SupportedPython {
    $Candidates = @(
        @{ Executable = "py.exe"; Prefix = @("-3.12") },
        @{ Executable = "py.exe"; Prefix = @("-3.11") },
        @{ Executable = "python.exe"; Prefix = @() }
    )

    foreach ($Candidate in $Candidates) {
        if (-not (Get-Command $Candidate.Executable -ErrorAction SilentlyContinue)) {
            continue
        }
        $Version = & $Candidate.Executable @($Candidate.Prefix) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $Version.Trim() -in @("3.11", "3.12")) {
            return $Candidate
        }
    }
    throw "Python 3.11 or 3.12 was not found. Install it from https://www.python.org/downloads/windows/ and rerun setup.bat."
}

if (-not (Test-Path -LiteralPath $Requirements -PathType Leaf)) {
    throw "requirements.txt was not found at $Requirements"
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    if ($CheckOnly) {
        throw "The virtual environment is missing. Run setup.bat first."
    }
    $Python = Find-SupportedPython
    Invoke-Checked "Creating .venv with Python $($Python.Prefix -join ' ')" $Python.Executable (@($Python.Prefix) + @("-m", "venv", $VenvDirectory))
}

$VenvVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "The existing .venv Python cannot run. Remove .venv and rerun setup.bat."
}
if ($VenvVersion.Trim() -notin @("3.11", "3.12")) {
    throw "The existing .venv uses Python $($VenvVersion.Trim()); Python 3.11 or 3.12 is required. Remove .venv and rerun setup.bat."
}
Write-Host "[OK] Using virtual environment Python $($VenvVersion.Trim())."

if (-not $CheckOnly) {
    Invoke-Checked "Upgrading pip, setuptools, and wheel" $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    Invoke-Checked "Installing backend and frontend dependencies" $VenvPython @("-m", "pip", "install", "-r", $Requirements)

    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        Copy-Item -LiteralPath $EnvTemplate -Destination $EnvFile
        Write-Host "[OK] Created backend\.env from the example file."
    } else {
        Write-Host "[OK] Preserved the existing backend\.env file."
    }
}

$Verification = @"
import fastapi
import uvicorn
import pydantic
import pydantic_settings
import aiosqlite
import httpx
import openai
import langchain
import langchain_openai
import langgraph
import langfuse
import playwright
import bs4
import pypdf
import pymupdf
import rapidocr
import onnxruntime
import numpy
import docx
import multipart
import PySide6
print('dependency verification passed')
"@
Invoke-Checked "Verifying required Python modules" $VenvPython @("-c", $Verification)

if ($CheckOnly) {
    Write-Host "[OK] Environment check completed without changing files."
} else {
    Write-Host "[OK] Installation completed. Add local API keys to backend\.env, then run start.bat."
}
