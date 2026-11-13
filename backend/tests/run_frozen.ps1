# Start NovelAgent.exe, wait for port, run frozen + interview tests, then stop.
# Usage (from backend dir): powershell -ExecutionPolicy Bypass -File tests\run_frozen.ps1
$ErrorActionPreference = "Stop"
$py = (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe" | Resolve-Path).Path
$exe = (Join-Path $PSScriptRoot "..\dist\NovelAgent.exe" | Resolve-Path).Path
$log = Join-Path $env:TEMP "novelagent.log"

if (-not (Test-Path $exe)) {
    Write-Host "EXE not found: $exe" -ForegroundColor Red
    exit 1
}

function Get-NovelAgentPort {
    if (Test-Path $log) {
        $lines = Get-Content $log -Tail 5 -ErrorAction SilentlyContinue
        foreach ($line in $lines) {
            if ($line -match '127\.0\.0\.1:(\d+)') { return [int]$Matches[1] }
        }
    }
    $pids = @(Get-Process NovelAgent -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    if ($pids.Count -eq 0) { return $null }
    $rows = netstat -ano | Select-String 'LISTENING'
    foreach ($row in $rows) {
        if ($row -match '127\.0\.0\.1:(\d+).*?(\d+)\s*$') {
            $port = [int]$Matches[1]
            $opid = [int]$Matches[2]
            if ($pids -contains $opid) { return $port }
        }
    }
    return $null
}

Write-Host "== stop existing NovelAgent ==" -ForegroundColor Cyan
Get-Process NovelAgent -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Remove-Item $log -ErrorAction SilentlyContinue

Write-Host "== start EXE ==" -ForegroundColor Cyan
$proc = Start-Process -FilePath $exe -PassThru
Write-Host "PID=$($proc.Id)"

$port = $null
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $port = Get-NovelAgentPort
    if ($port) { break }
}

if (-not $port) {
    Write-Host "No listening port within 45s" -ForegroundColor Red
    if (Test-Path $log) { Get-Content $log -Tail 30 }
    Get-Process NovelAgent -ErrorAction SilentlyContinue | Stop-Process -Force
    exit 1
}

if (-not $env:NOVEL_AGENT_API_KEY) {
    Write-Host "Frozen EXE tests require NOVEL_AGENT_API_KEY environment variable" -ForegroundColor Red
    Get-Process NovelAgent -ErrorAction SilentlyContinue | Stop-Process -Force
    exit 1
}

Write-Host "== port $port detected, configuring API key ==" -ForegroundColor Green
& $py -c "import httpx, os; c=httpx.Client(base_url='http://127.0.0.1:$port', timeout=30); c.put('/api/config', json={'api_key': os.environ['NOVEL_AGENT_API_KEY']})"

Write-Host "== running tests ==" -ForegroundColor Green
& $py (Join-Path $PSScriptRoot "frozen_test.py") $port
if ($LASTEXITCODE -ne 0) {
    Get-Process NovelAgent -ErrorAction SilentlyContinue | Stop-Process -Force
    exit $LASTEXITCODE
}
& $py (Join-Path $PSScriptRoot "interview_test.py") $port
$code2 = $LASTEXITCODE

Write-Host "== stop EXE ==" -ForegroundColor Cyan
Get-Process NovelAgent -ErrorAction SilentlyContinue | Stop-Process -Force

if ($code2 -ne 0) {
    Write-Host "interview test failed exit=$code2" -ForegroundColor Red
    exit $code2
}
Write-Host "All frozen tests passed" -ForegroundColor Green
