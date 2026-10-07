# 重置「今日学习」，让生成练习卷按钮可以重新走一遍完整流程
#
# 背景：产品规则规定「同一天不能重新生成整卷」，所以点过一次生成后，
# 再进 /study 会直接进入答题态。要重新演示，必须先清掉今天的计划。
#
# 用法（项目根执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\reset-today.ps1

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host '正在重置今日计划、练习历史与叶子状态投影…' -ForegroundColor Cyan
python scripts\reset_today.py
if ($LASTEXITCODE -ne 0) {
    Write-Host '重置失败：请确认 PostgreSQL 与后端数据库配置可用。' -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host '已重置。现在打开（或刷新）http://127.0.0.1:5173/study' -ForegroundColor Green
Write-Host '  会重新出现准备页与推荐列表，「生成今日练习卷」按钮可以再次点击。' -ForegroundColor Green