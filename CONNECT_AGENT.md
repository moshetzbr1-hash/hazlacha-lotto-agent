name: Double Lotto Israel Agent

on:
  workflow_dispatch:
    inputs:
      command:
        description: "Run command"
        required: true
        default: "fetch"
        type: choice
        options:
          - fetch
          - report
          - fetch_and_report
  schedule:
    # GitHub Actions uses UTC. Israel is UTC+2 in winter and UTC+3 in daylight saving time.
    # These two runs cover 23:30 Asia/Jerusalem across seasonal clock changes.
    # Duplicate draws are safely updated/deduplicated by lotto_agent.py.
    - cron: "30 20 * * 2,6"
    - cron: "30 21 * * 2,6"
    # Bi-monthly statistical report, first day of every odd month at 09:00/08:00 Israel time depending on DST.
    - cron: "0 6 1 1,3,5,7,9,11 *"

permissions:
  contents: write

jobs:
  run-agent:
    runs-on: ubuntu-latest
    env:
      TZ: Asia/Jerusalem

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Decide command
        id: decide
        shell: bash
        run: |
          if [[ "${{ github.event_name }}" == "workflow_dispatch" ]]; then
            echo "cmd=${{ inputs.command }}" >> "$GITHUB_OUTPUT"
          else
            # Report schedule: day 1 at 06:00 UTC.
            if [[ "$(date -u +%d%H%M)" == "010600" ]]; then
              echo "cmd=report" >> "$GITHUB_OUTPUT"
            else
              echo "cmd=fetch" >> "$GITHUB_OUTPUT"
            fi
          fi

      - name: Run fetch
        if: steps.decide.outputs.cmd == 'fetch' || steps.decide.outputs.cmd == 'fetch_and_report'
        run: |
          python lotto_agent.py fetch \
            --csv lotto_history.csv \
            --json lotto_history.json \
            --log lotto_agent.log

      - name: Run report
        if: steps.decide.outputs.cmd == 'report' || steps.decide.outputs.cmd == 'fetch_and_report'
        run: |
          python lotto_agent.py report \
            --json lotto_history.json \
            --out lotto_stats_report.json \
            --log lotto_agent.log

      - name: Commit updated history/report/log
        shell: bash
        run: |
          git config user.name "double-lotto-agent"
          git config user.email "double-lotto-agent@users.noreply.github.com"
          git add lotto_history.csv lotto_history.json lotto_stats_report.json lotto_agent.log
          if git diff --cached --quiet; then
            echo "No changes to commit."
          else
            git commit -m "Update double lotto agent data"
            git push
          fi
