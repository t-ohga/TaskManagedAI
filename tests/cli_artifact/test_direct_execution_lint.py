"""Sprint 6 Batch 3: AI output direct execution lint の契約テスト。"""

from __future__ import annotations

import dataclasses
from typing import get_args, get_type_hints

import pytest

from backend.app.services.cli_artifact.direct_execution_lint import (
    ArtifactEdge,
    ArtifactKind,
    ArtifactNode,
    ArtifactSource,
    DirectExecutionViolation,
    LintResult,
    lint_artifact_graph,
)


def _single_edge_result(
    *,
    parent_source: ArtifactSource,
    child_kind: ArtifactKind,
) -> LintResult:
    nodes = (
        ArtifactNode(
            artifact_id="parent",
            source=parent_source,
            kind=ArtifactKind.CLI_STDOUT,
        ),
        ArtifactNode(
            artifact_id="child",
            source=ArtifactSource.AI,
            kind=child_kind,
        ),
    )
    edges = (ArtifactEdge(parent_artifact_id="parent", child_artifact_id="child"),)
    return lint_artifact_graph(nodes=nodes, edges=edges)


def _assert_single_violation(
    result: LintResult,
    *,
    parent_source: ArtifactSource,
    child_kind: ArtifactKind,
) -> DirectExecutionViolation:
    assert result.is_clean is False
    assert len(result.violations) == 1

    violation = result.violations[0]
    assert violation.parent_artifact_id == "parent"
    assert violation.parent_source is parent_source
    assert violation.child_artifact_id == "child"
    assert violation.child_kind is child_kind
    assert violation.reason == "ai_source_to_forbidden_sink"
    return violation


def _assert_graph_integrity_violation(
    result: LintResult,
    *,
    parent_artifact_id: str,
    parent_source: ArtifactSource | None,
    child_artifact_id: str,
    child_kind: ArtifactKind | None,
) -> DirectExecutionViolation:
    assert result.is_clean is False
    assert len(result.violations) == 1

    violation = result.violations[0]
    assert violation.parent_artifact_id == parent_artifact_id
    assert violation.parent_source is parent_source
    assert violation.child_artifact_id == child_artifact_id
    assert violation.child_kind is child_kind
    assert violation.reason == "graph_integrity_unknown_node"
    return violation


def _assert_clean(result: LintResult) -> None:
    assert result.violations == ()
    assert result.is_clean is True


def _violation() -> DirectExecutionViolation:
    return DirectExecutionViolation(
        parent_artifact_id="parent",
        parent_source=ArtifactSource.AI,
        child_artifact_id="child",
        child_kind=ArtifactKind.SHELL_COMMAND,
        reason="ai_source_to_forbidden_sink",
    )


def test_artifact_source_enum_5_values() -> None:
    """ArtifactSource は AI 境界で使う 5 値固定とする。"""

    assert tuple(source.value for source in ArtifactSource) == (
        "ai",
        "cli_launcher",
        "trusted",
        "runner",
        "human",
    )


def test_artifact_kind_enum_includes_all_cli_kinds() -> None:
    """CLI artifact kind は lint graph の enum に揃っている。"""

    actual = {kind.value for kind in ArtifactKind}

    assert {
        "cli_input",
        "cli_stdout",
        "cli_stderr",
        "cli_exit",
        "cli_result_summary",
    } <= actual


def test_artifact_kind_enum_includes_all_sink_kinds() -> None:
    """mutation sink kind は fail-closed lint の対象として enum 化される。"""

    actual = {kind.value for kind in ArtifactKind}

    assert {
        "shell_command",
        "sql_statement",
        "migration",
        "workflow_file",
        "external_tool_call",
        "repo_patch_applied",
    } <= actual


def test_ai_source_to_shell_command_is_violation() -> None:
    """AI 出力から shell command への直結は禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.SHELL_COMMAND,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.SHELL_COMMAND,
    )


def test_ai_source_to_sql_statement_is_violation() -> None:
    """AI 出力から SQL statement への直結は禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.SQL_STATEMENT,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.SQL_STATEMENT,
    )


def test_ai_source_to_migration_is_violation() -> None:
    """AI 出力から migration apply 相当 artifact への直結は禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.MIGRATION,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.MIGRATION,
    )


def test_ai_source_to_workflow_file_is_violation() -> None:
    """AI 出力から workflow file への直結は禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.WORKFLOW_FILE,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.WORKFLOW_FILE,
    )


def test_ai_source_to_external_tool_call_is_violation() -> None:
    """AI 出力から external tool call への直結は禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.EXTERNAL_TOOL_CALL,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.EXTERNAL_TOOL_CALL,
    )


def test_ai_source_to_repo_patch_applied_is_violation() -> None:
    """AI 出力から repo patch applied への直結は禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.REPO_PATCH_APPLIED,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.REPO_PATCH_APPLIED,
    )


def test_cli_launcher_source_to_shell_command_is_violation() -> None:
    """CLI launcher output も AI-like source として shell 直結を禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.CLI_LAUNCHER,
        child_kind=ArtifactKind.SHELL_COMMAND,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.CLI_LAUNCHER,
        child_kind=ArtifactKind.SHELL_COMMAND,
    )


def test_cli_launcher_source_to_sql_statement_is_violation() -> None:
    """CLI launcher output も AI-like source として SQL 直結を禁止する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.CLI_LAUNCHER,
        child_kind=ArtifactKind.SQL_STATEMENT,
    )

    _assert_single_violation(
        result,
        parent_source=ArtifactSource.CLI_LAUNCHER,
        child_kind=ArtifactKind.SQL_STATEMENT,
    )


def test_trusted_source_to_shell_command_is_allowed() -> None:
    """trusted source は approval gate 通過済みとして shell sink を許可する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.TRUSTED,
        child_kind=ArtifactKind.SHELL_COMMAND,
    )

    _assert_clean(result)


def test_runner_source_to_repo_patch_applied_is_allowed() -> None:
    """runner source は runner gateway 通過済みとして patch apply sink を許可する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.RUNNER,
        child_kind=ArtifactKind.REPO_PATCH_APPLIED,
    )

    _assert_clean(result)


def test_human_source_to_workflow_file_is_allowed() -> None:
    """human source は AI output boundary の direct violation ではない。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.HUMAN,
        child_kind=ArtifactKind.WORKFLOW_FILE,
    )

    _assert_clean(result)


def test_ai_source_to_plan_is_allowed() -> None:
    """AI 出力から plan への変換は intermediate artifact として許可する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.PLAN,
    )

    _assert_clean(result)


def test_ai_source_to_evidence_is_allowed() -> None:
    """AI 出力から evidence への変換は mutation sink ではない。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.EVIDENCE,
    )

    _assert_clean(result)


def test_ai_source_to_cli_input_is_allowed() -> None:
    """AI 出力から cli_input への変換は直接実行 sink ではない。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.CLI_INPUT,
    )

    _assert_clean(result)


def test_ai_source_to_patch_is_allowed() -> None:
    """patch artifact 自体は intermediate であり apply edge とは分離する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.PATCH,
    )

    _assert_clean(result)


def test_lint_finds_multiple_violations() -> None:
    """単一 graph 内の複数 forbidden edge を全て返す。"""

    nodes = (
        ArtifactNode("ai-output", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),
        ArtifactNode("shell", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),
        ArtifactNode("sql", ArtifactSource.AI, ArtifactKind.SQL_STATEMENT),
        ArtifactNode("plan", ArtifactSource.AI, ArtifactKind.PLAN),
    )
    edges = (
        ArtifactEdge("ai-output", "shell"),
        ArtifactEdge("ai-output", "plan"),
        ArtifactEdge("ai-output", "sql"),
    )

    result = lint_artifact_graph(nodes=nodes, edges=edges)

    assert result.is_clean is False
    assert tuple(v.child_artifact_id for v in result.violations) == (
        "shell",
        "sql",
    )
    assert tuple(v.child_kind for v in result.violations) == (
        ArtifactKind.SHELL_COMMAND,
        ArtifactKind.SQL_STATEMENT,
    )


def test_lint_finds_violations_in_complex_graph() -> None:
    """5 nodes / 4 edges の graph でも AI-like source 直結だけを検出する。"""

    nodes = (
        ArtifactNode("ai-output", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),
        ArtifactNode("shell", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),
        ArtifactNode("plan", ArtifactSource.AI, ArtifactKind.PLAN),
        ArtifactNode("trusted-plan", ArtifactSource.TRUSTED, ArtifactKind.PLAN),
        ArtifactNode("workflow", ArtifactSource.HUMAN, ArtifactKind.WORKFLOW_FILE),
    )
    edges = (
        ArtifactEdge("ai-output", "shell"),
        ArtifactEdge("ai-output", "plan"),
        ArtifactEdge("trusted-plan", "workflow"),
        ArtifactEdge("plan", "workflow"),
    )

    result = lint_artifact_graph(nodes=nodes, edges=edges)

    assert result.is_clean is False
    assert len(result.violations) == 2
    assert tuple(v.parent_artifact_id for v in result.violations) == (
        "ai-output",
        "plan",
    )
    assert tuple(v.child_artifact_id for v in result.violations) == (
        "shell",
        "workflow",
    )


def test_lint_reports_graph_integrity_violation_for_unknown_parent_id() -> None:
    """未知 parent node を持つ edge は graph integrity violation として返す。"""

    nodes = (
        ArtifactNode("child", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),
    )
    edges = (
        ArtifactEdge("missing-parent", "child"),
    )

    result = lint_artifact_graph(nodes=nodes, edges=edges)

    _assert_graph_integrity_violation(
        result,
        parent_artifact_id="missing-parent",
        parent_source=None,
        child_artifact_id="child",
        child_kind=ArtifactKind.SHELL_COMMAND,
    )


def test_lint_reports_graph_integrity_violation_for_unknown_child_id() -> None:
    """未知 child node を持つ edge は graph integrity violation として返す。"""

    nodes = (
        ArtifactNode("parent", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),
    )
    edges = (
        ArtifactEdge("parent", "missing-child"),
    )

    result = lint_artifact_graph(nodes=nodes, edges=edges)

    _assert_graph_integrity_violation(
        result,
        parent_artifact_id="parent",
        parent_source=ArtifactSource.AI,
        child_artifact_id="missing-child",
        child_kind=None,
    )


def test_lint_reports_multiple_graph_integrity_violations() -> None:
    """複数の欠損 node edge は silent skip せず全件 violation として返す。"""

    nodes = (
        ArtifactNode("parent", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),
        ArtifactNode("child", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),
    )
    edges = (
        ArtifactEdge("missing-parent", "child"),
        ArtifactEdge("parent", "missing-child"),
    )

    result = lint_artifact_graph(nodes=nodes, edges=edges)

    assert result.is_clean is False
    assert len(result.violations) == 2
    assert tuple(v.reason for v in result.violations) == (
        "graph_integrity_unknown_node",
        "graph_integrity_unknown_node",
    )
    assert tuple(v.parent_artifact_id for v in result.violations) == (
        "missing-parent",
        "parent",
    )
    assert tuple(v.parent_source for v in result.violations) == (
        None,
        ArtifactSource.AI,
    )
    assert tuple(v.child_artifact_id for v in result.violations) == (
        "child",
        "missing-child",
    )
    assert tuple(v.child_kind for v in result.violations) == (
        ArtifactKind.SHELL_COMMAND,
        None,
    )


def test_lint_clean_when_no_edges() -> None:
    """edge が無い graph は direct execution 経路が無いため clean になる。"""

    nodes = (
        ArtifactNode("ai-output", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),
        ArtifactNode("shell", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),
    )

    result = lint_artifact_graph(nodes=nodes, edges=())

    _assert_clean(result)


def test_lint_clean_when_no_violations() -> None:
    """sink を含んでも trusted 経由や intermediate だけなら clean になる。"""

    nodes = (
        ArtifactNode("ai-output", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),
        ArtifactNode("patch", ArtifactSource.AI, ArtifactKind.PATCH),
        ArtifactNode("trusted", ArtifactSource.TRUSTED, ArtifactKind.PLAN),
        ArtifactNode("shell", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),
    )
    edges = (
        ArtifactEdge("ai-output", "patch"),
        ArtifactEdge("trusted", "shell"),
    )

    result = lint_artifact_graph(nodes=nodes, edges=edges)

    _assert_clean(result)


def test_lint_result_is_clean_when_violations_empty() -> None:
    """violations が空なら LintResult.is_clean は True になる。"""

    result = LintResult(violations=())

    assert result.is_clean is True


def test_lint_result_is_not_clean_when_violations_present() -> None:
    """violations が 1 件以上あれば LintResult.is_clean は False になる。"""

    result = LintResult(violations=(_violation(),))

    assert result.is_clean is False


def test_lint_result_is_frozen() -> None:
    """LintResult は caller が後から mutation できない frozen dataclass とする。"""

    result = LintResult(violations=())

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.violations = (_violation(),)


def test_violation_includes_parent_source_and_child_kind() -> None:
    """violation は parent source と child kind を監査可能に保持する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.CLI_LAUNCHER,
        child_kind=ArtifactKind.EXTERNAL_TOOL_CALL,
    )

    violation = _assert_single_violation(
        result,
        parent_source=ArtifactSource.CLI_LAUNCHER,
        child_kind=ArtifactKind.EXTERNAL_TOOL_CALL,
    )
    assert violation.parent_source is ArtifactSource.CLI_LAUNCHER
    assert violation.child_kind is ArtifactKind.EXTERNAL_TOOL_CALL


def test_violation_reason_is_literal_ai_source_to_forbidden_sink() -> None:
    """violation reason は caller が分岐しやすい literal 値に固定する。"""

    result = _single_edge_result(
        parent_source=ArtifactSource.AI,
        child_kind=ArtifactKind.MIGRATION,
    )

    violation = result.violations[0]

    assert violation.reason == "ai_source_to_forbidden_sink"


def test_violation_reason_can_be_graph_integrity_unknown_node() -> None:
    """violation reason の Literal 型は graph integrity violation も許可する。"""

    reason_type = get_type_hints(DirectExecutionViolation)["reason"]
    violation = DirectExecutionViolation(
        parent_artifact_id="missing-parent",
        parent_source=None,
        child_artifact_id="child",
        child_kind=ArtifactKind.SHELL_COMMAND,
        reason="graph_integrity_unknown_node",
    )

    assert set(get_args(reason_type)) == {
        "ai_source_to_forbidden_sink",
        "graph_integrity_unknown_node",
    }
    assert violation.reason == "graph_integrity_unknown_node"


def test_violation_parent_source_is_none_when_parent_unknown() -> None:
    """parent node が未知の場合、parent_source は監査上 None として残す。"""

    result = lint_artifact_graph(
        nodes=(ArtifactNode("child", ArtifactSource.AI, ArtifactKind.SHELL_COMMAND),),
        edges=(ArtifactEdge("missing-parent", "child"),),
    )

    violation = result.violations[0]

    assert violation.reason == "graph_integrity_unknown_node"
    assert violation.parent_artifact_id == "missing-parent"
    assert violation.parent_source is None
    assert violation.child_artifact_id == "child"
    assert violation.child_kind is ArtifactKind.SHELL_COMMAND


def test_violation_child_kind_is_none_when_child_unknown() -> None:
    """child node が未知の場合、child_kind は監査上 None として残す。"""

    result = lint_artifact_graph(
        nodes=(ArtifactNode("parent", ArtifactSource.AI, ArtifactKind.CLI_STDOUT),),
        edges=(ArtifactEdge("parent", "missing-child"),),
    )

    violation = result.violations[0]

    assert violation.reason == "graph_integrity_unknown_node"
    assert violation.parent_artifact_id == "parent"
    assert violation.parent_source is ArtifactSource.AI
    assert violation.child_artifact_id == "missing-child"
    assert violation.child_kind is None


def test_violation_dataclass_is_frozen() -> None:
    """DirectExecutionViolation は監査 record として immutable にする。"""

    violation = _violation()

    with pytest.raises(dataclasses.FrozenInstanceError):
        violation.reason = "mutated"


def test_artifact_node_dataclass_is_frozen() -> None:
    """ArtifactNode は lint 中に source / kind を mutation できない。"""

    node = ArtifactNode(
        artifact_id="artifact-1",
        source=ArtifactSource.AI,
        kind=ArtifactKind.CLI_STDOUT,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        node.kind = ArtifactKind.SHELL_COMMAND