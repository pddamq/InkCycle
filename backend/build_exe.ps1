# 打包 NovelAgent 为单文件 EXE（默认无控制台窗口）
# 用法（在 backend 目录）：powershell -ExecutionPolicy Bypass -File build_exe.ps1 [-Console]
param(
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"

Write-Host "== 检查前端构建产物 ==" -ForegroundColor Cyan
$dist = "..\frontend\dist"
if (-not (Test-Path "$dist\index.html")) {
    Write-Host "未找到前端 dist，请先在 frontend 目录执行 pnpm build" -ForegroundColor Red
    exit 1
}

# 默认 --windowed（无 CMD）；加 -Console 生成带控制台的调试版
$consoleFlag = if ($Console) { "--console" } else { "--windowed" }
$name = if ($Console) { "NovelAgent_debug" } else { "NovelAgent" }

Write-Host "== 清理旧构建（保留 dist/data 用户数据）==" -ForegroundColor Cyan
Remove-Item build, "$name.spec" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "dist\$name.exe", "dist\${name}_debug.exe" -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path dist | Out-Null

Write-Host "== 运行 PyInstaller（$name）==" -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean --onefile $consoleFlag `
    --name $name `
    --add-data "..\frontend\dist;frontend_dist" `
    --add-data "novel_agent\builtin_skills;builtin_skills" `
    --collect-submodules uvicorn `
    --collect-submodules novel_agent `
    --collect-all webview `
    --collect-all clr_loader `
    --collect-all pythonnet `
    --hidden-import multipart `
    run.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller 失败" -ForegroundColor Red
    exit 1
}

$exe = "dist\$name.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "== 完成：$exe （$size MB）==" -ForegroundColor Green
} else {
    Write-Host "未生成 exe" -ForegroundColor Red
    exit 1
}
