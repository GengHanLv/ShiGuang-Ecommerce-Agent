# 本地一键启动器：只启动本项目，不安装依赖、不修改或停止Docker容器。
param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 5173,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$pythonFile = Join-Path $taskRoot '.venv\Scripts\python.exe'
$viteFile = Join-Path $taskRoot 'frontend\node_modules\vite\bin\vite.js'
$runtime = Join-Path $taskRoot 'data\logs\startup'
$started = @()
if ($BackendPort -lt 1024 -or $BackendPort -gt 65535 -or $FrontendPort -lt 1024 -or $FrontendPort -gt 65535 -or $BackendPort -eq $FrontendPort) { throw '启动端口必须不同且在1024到65535之间。' }

function Listener-Pid([int]$Port) {
    $item = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($item) { return [int]$item.OwningProcess }
    return 0
}
function Probe([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        # Windows PowerShell 5会将无charset的HTML按Latin-1解码，使用原始字节按UTF-8读取。
        return [System.Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
    } catch { return $null }
}
function Wait-Ready([string]$Url) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Probe $Url) { return }
        Start-Sleep -Seconds 1
    }
    throw "服务未及时就绪：$Url；请查看 data/logs/startup 下启动日志。"
}

try {
    foreach ($required in @($pythonFile, $viteFile, (Join-Path $taskRoot '.env'))) {
        if (-not (Test-Path -LiteralPath $required)) { throw "缺少 $required；请先按README配置Python环境、前端依赖和.env。" }
    }
    $nodeFile = (Get-Command node.exe -ErrorAction Stop).Source
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backendUrl = "http://127.0.0.1:$BackendPort"
    $frontendUrl = "http://127.0.0.1:$FrontendPort"
    $backendPid = Listener-Pid $BackendPort
    if ($backendPid) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$backendPid"
        if ($processInfo.CommandLine -notlike "*$pythonFile*uvicorn backend.app.main:app*" -or -not (Probe "$backendUrl/health")) {
            throw "后端端口 $BackendPort 被其他服务占用，未结束任何进程。"
        }
        $schema = Probe "$backendUrl/openapi.json"
        if (-not $schema -or -not $schema.Contains('"/documents/from-task/{identifier}"')) {
            throw '当前后端尚未加载 PDF 导出接口，请停止旧后端并重新运行启动器，不能只刷新前端。'
        }
        Write-Host "复用已运行的本项目后端：$backendUrl"
    } else {
        $proc = Start-Process -FilePath $pythonFile -ArgumentList @('-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port',"$BackendPort") -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "backend-$stamp.stdout.log") -RedirectStandardError (Join-Path $runtime "backend-$stamp.stderr.log")
        $started += $proc.Id
        Wait-Ready "$backendUrl/health"
        $backendPid = Listener-Pid $BackendPort
        Write-Host "后端已启动：$backendUrl"
    }
    $frontendPid = Listener-Pid $FrontendPort
    if ($frontendPid) {
        # 先核实页面标题；不把端口上的其他网站当成本项目，也不杀占用进程。
        $expectedTitle = [regex]::Match((Get-Content -LiteralPath (Join-Path $taskRoot 'frontend\index.html') -Raw -Encoding UTF8), '<title>(.*?)</title>').Groups[1].Value
        $html = Probe $frontendUrl
        if (-not $expectedTitle -or -not $html -or -not $html.Contains("<title>$expectedTitle</title>")) { throw "前端端口 $FrontendPort 被其他服务占用。" }
        $proxyHealth = Probe "$frontendUrl/api/health"
        if (-not $proxyHealth) { throw '已有前端的API代理不可用；请关闭该前端后重新启动。' }
        Write-Host "复用已运行的本项目前端：$frontendUrl"
    } else {
        # Vite继承环境变量，使前端/api准确转发到本次后端端口。
        $env:API_PROXY_TARGET = $backendUrl
        $proc = Start-Process -FilePath $nodeFile -ArgumentList @(('"' + $viteFile + '"'),'--host','127.0.0.1','--port',"$FrontendPort",'--strictPort') -WorkingDirectory (Join-Path $taskRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "frontend-$stamp.stdout.log") -RedirectStandardError (Join-Path $runtime "frontend-$stamp.stderr.log")
        $started += $proc.Id
        Wait-Ready $frontendUrl
        if (-not (Probe "$frontendUrl/api/health")) { throw '前端已启动，但API代理探测失败。' }
        $frontendPid = Listener-Pid $FrontendPort
        Write-Host "前端已启动：$frontendUrl"
    }
    @{backend_pid=$backendPid;frontend_pid=$frontendPid;backend_port=$BackendPort;frontend_port=$FrontendPort;started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'preview-processes.json') -Encoding UTF8
    Write-Host 'Redis/MySQL/Milvus需要Docker容器已运行；启动器不会更改容器。'
    Write-Host "API文档：$backendUrl/docs"
    Write-Host '首次知识检索需要加载BGE模型，可能等待较久。'
    if (-not $NoBrowser) { Start-Process $frontendUrl }
    exit 0
} catch {
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    if ($started.Count) { Write-Host "本次已启动的进程ID：$($started -join ', ')；可检查data/logs/startup日志，启动器不会自动结束已有服务。" }
    exit 1
}
