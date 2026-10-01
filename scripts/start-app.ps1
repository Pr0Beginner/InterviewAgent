$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$frontendPath = Join-Path $projectRoot "frontend"
$healthUrl = "http://127.0.0.1:8000/api/health"
$backendProcess = $null
$backendListenerPid = $null
$backendStartedHere = $false
$clientExitCode = 1

function Test-BackendHealth {
    <# 仅当本地 FastAPI 健康检查接口可访问且状态正常时返回 true。 #>
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1
        return $response.status -eq "ok"
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment was not found: $pythonPath"
}

if (-not (Test-BackendHealth)) {
    $backendProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -PassThru
    $backendStartedHere = $true

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (Test-BackendHealth) {
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not (Test-BackendHealth)) {
        throw "Backend did not become ready within 10 seconds."
    }

    # Windows 虚拟环境启动器可能派生实际监听进程，记录真正占用端口的 PID。
    $listener = Get-NetTCPConnection `
        -LocalPort 8000 `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $listener) {
        $backendListenerPid = $listener.OwningProcess
    }
}

try {
    Push-Location $frontendPath
    & $pythonPath -m client.main
    $clientExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    if ($backendStartedHere) {
        if ($null -ne $backendListenerPid) {
            Stop-Process -Id $backendListenerPid -ErrorAction SilentlyContinue
        }
        if ($null -ne $backendProcess -and -not $backendProcess.HasExited) {
            Stop-Process -Id $backendProcess.Id -ErrorAction SilentlyContinue
            $backendProcess.WaitForExit()
        }
    }
}

exit $clientExitCode
