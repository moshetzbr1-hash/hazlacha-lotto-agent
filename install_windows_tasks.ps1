# Install Double Lotto Israel Agent as Windows Scheduled Tasks.
# Run PowerShell as the current user from the folder containing lotto_agent.py.

$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    Write-Error "Python was not found. Install Python 3.11+ first."
    exit 1
}

$FetchAction = New-ScheduledTaskAction -Execute $Python -Argument "lotto_agent.py fetch --csv lotto_history.csv --json lotto_history.json --log lotto_agent.log" -WorkingDirectory $AgentDir
$ReportAction = New-ScheduledTaskAction -Execute $Python -Argument "lotto_agent.py report --json lotto_history.json --out lotto_stats_report.json --log lotto_agent.log" -WorkingDirectory $AgentDir

$TueTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At 23:30
$SatTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 23:30

Register-ScheduledTask -TaskName "DoubleLottoAgent-Fetch-Tuesday" -Action $FetchAction -Trigger $TueTrigger -Description "Fetch Israeli Double Lotto result every Tuesday at 23:30" -Force
Register-ScheduledTask -TaskName "DoubleLottoAgent-Fetch-Saturday" -Action $FetchAction -Trigger $SatTrigger -Description "Fetch Israeli Double Lotto result every Saturday at 23:30" -Force

# Windows Task Scheduler has limited native "every two months" support in simple scripts.
# This runs monthly on the 1st at 09:00; the script/log can be checked, or leave it as monthly for more reports.
$MonthlyTrigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At 09:00
Register-ScheduledTask -TaskName "DoubleLottoAgent-Report-Monthly" -Action $ReportAction -Trigger $MonthlyTrigger -Description "Generate Lotto statistics report monthly; keep every second month if desired" -Force

Write-Host "Installed Windows Scheduled Tasks for Double Lotto Israel Agent."
Write-Host "Test now with: python lotto_agent.py fetch"
