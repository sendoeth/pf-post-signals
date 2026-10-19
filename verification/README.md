Verification run 2026-10-19 (task_ce2bc359 verification request evt_3a44ed9e08d2c151f6a0b045).

Commands, from the repo root:

    python3 score.py        > verification/score_py_output.txt
    python3 make_report.py  > verification/make_report_py_output.txt

Both exit 0. After this run RESULTS.md and data/comparison.json are byte-identical to the
originally published commit 9541c246 (headline numbers unchanged).

Change in this commit: old-pipeline rows in data/old_system_decisions.json now also store the
exit date and price per horizon (they previously stored entry and returns only). Returns are
unchanged; exits are the Binance UTC closes from data/prices.json.
