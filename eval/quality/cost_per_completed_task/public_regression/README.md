# AC-KPI-05 Public Regression

This split contains the public regression fixture for `cost_per_completed_task`.

The sample is intentionally small and deterministic:
- 5 sample AgentRun rows
- 3 completed rows
- 1 failed row
- 1 cancelled row
- completed cost total: USD 0.60
- cost per completed task: USD 0.20

Only `status=completed` rows contribute to `total_completed_runs`, `total_cost_usd`, and `cost_per_completed_task_usd`.

