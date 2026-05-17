"""Hard-gate aggregators for TaskManagedAI Eval Harness.

Each aggregator validates a fixture corpus loaded by
:func:`backend.app.services.eval.loader.load_fixture_corpus` against
the AC-HARD-NN hard-gate contract. Aggregators are pure functions (no
DB / file system / network access).

F-PR37-002 adopt (code-reviewer R1 LOW): actual re-export per plan
batch 5j §4.1 (previously this module was empty).
"""

from backend.app.services.eval.hard_gates.backup_restore import (
    AC_HARD_04_EXPECTED_DECISION,
    AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS,
    AC_HARD_04_GATE_ID,
    AC_HARD_04_METRIC_KEY,
    AC_HARD_04_PATTERN_HIT_KIND,
    AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM,
    AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON,
    AC_HARD_04_RPO_HOURS_MAX,
    AC_HARD_04_RTO_HOURS_MAX,
    AC_HARD_04_THRESHOLD,
    BackupRestoreFixtureResult,
    BackupRestoreMetricResult,
    evaluate_backup_restore_rpo_rto,
)
from backend.app.services.eval.hard_gates.tenant_isolation import (
    AC_HARD_03_EXPECTED_DECISION,
    AC_HARD_03_EXPECTED_FAILURE,
    AC_HARD_03_EXPECTED_REASON_CODE,
    AC_HARD_03_GATE_ID,
    AC_HARD_03_METRIC_KEY,
    AC_HARD_03_PATTERN_HIT_KIND,
    AC_HARD_03_REQUIRED_OPERATION_CLASSES,
    AC_HARD_03_THRESHOLD,
    TenantIsolationFixtureResult,
    TenantIsolationMetricResult,
    evaluate_tenant_isolation_negative_pass,
)

__all__ = [
    # AC-HARD-03 tenant_isolation (batch 5b)
    "AC_HARD_03_EXPECTED_DECISION",
    "AC_HARD_03_EXPECTED_FAILURE",
    "AC_HARD_03_EXPECTED_REASON_CODE",
    "AC_HARD_03_GATE_ID",
    "AC_HARD_03_METRIC_KEY",
    "AC_HARD_03_PATTERN_HIT_KIND",
    "AC_HARD_03_REQUIRED_OPERATION_CLASSES",
    "AC_HARD_03_THRESHOLD",
    "TenantIsolationFixtureResult",
    "TenantIsolationMetricResult",
    "evaluate_tenant_isolation_negative_pass",
    # AC-HARD-04 backup_restore (batch 5j)
    "AC_HARD_04_EXPECTED_DECISION",
    "AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS",
    "AC_HARD_04_GATE_ID",
    "AC_HARD_04_METRIC_KEY",
    "AC_HARD_04_PATTERN_HIT_KIND",
    "AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM",
    "AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON",
    "AC_HARD_04_RPO_HOURS_MAX",
    "AC_HARD_04_RTO_HOURS_MAX",
    "AC_HARD_04_THRESHOLD",
    "BackupRestoreFixtureResult",
    "BackupRestoreMetricResult",
    "evaluate_backup_restore_rpo_rto",
]
