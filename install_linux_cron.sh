{
  "agent_name": "ההצלחה שלי",
  "status": "ready_for_external_activation",
  "cannot_run_inside_chatgpt_background": true,
  "activation_options": [
    "GitHub Actions workflow included at .github/workflows/double_lotto_agent.yml",
    "Linux cron installer included at install_linux_cron.sh",
    "Windows scheduled tasks installer included at install_windows_tasks.ps1"
  ],
  "schedule": {
    "fetch": "Tuesday and Saturday at 23:30 Asia/Jerusalem",
    "report": "Every two months"
  },
  "data_files": [
    "lotto_history.csv",
    "lotto_history.json",
    "lotto_stats_report.json",
    "lotto_agent.log"
  ],
  "created_at": "2026-05-16T19:41:33.522781+00:00"
}