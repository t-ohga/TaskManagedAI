# AC-KPI-05 cost_per_completed_task

This dataset skeleton defines the AC-KPI-05 `cost_per_completed_task` quality KPI.

Metric definition:

`cost_per_completed_task_usd = total_cost_usd for completed runs / total_completed_runs`

Rules:

- Count only AgentRun rows with `status=completed`.
- Exclude `failed`, `cancelled`, `provider_refused`, `repair_exhausted`, and non-terminal in-progress states.
- Use normalized provider usage after BudgetGuard accounting.
- Keep fixture hashes immutable through `manifest.json`.
- Keep private holdout and adversarial expectations out of implementation and prompt tuning.
- Threshold for the skeleton is USD 0.50 per completed task.

