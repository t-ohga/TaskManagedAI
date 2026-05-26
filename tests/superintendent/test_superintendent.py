"""SP-035: Superintendent delegation policy + lifecycle + dispatch tests."""

from __future__ import annotations

from uuid import uuid4

from backend.app.services.superintendent.delegation_policy import (
    IMMUTABLE_FORBIDDEN_ACTIONS,
    POLICY_TEMPLATES,
    DelegationPolicy,
    can_auto_approve,
    is_action_allowed,
)
from backend.app.services.superintendent.dispatch import (
    DispatchRequest,
    evaluate_dispatch,
)
from backend.app.services.superintendent.lifecycle import (
    TERMINAL_STATES,
    can_transition,
)


class TestDelegationPolicy:
    def test_immutable_forbidden_actions_includes_approval_decide(self) -> None:
        assert "approval_decide" in IMMUTABLE_FORBIDDEN_ACTIONS
        assert "merge" in IMMUTABLE_FORBIDDEN_ACTIONS
        assert "deploy" in IMMUTABLE_FORBIDDEN_ACTIONS
        assert "secret_access" in IMMUTABLE_FORBIDDEN_ACTIONS
        assert "provider_call" in IMMUTABLE_FORBIDDEN_ACTIONS

    def test_forbidden_actions_cannot_be_overridden(self) -> None:
        policy = DelegationPolicy(forbidden_actions=frozenset({"only_merge"}))
        assert policy.forbidden_actions == IMMUTABLE_FORBIDDEN_ACTIONS

    def test_conservative_template(self) -> None:
        p = POLICY_TEMPLATES["conservative"]
        assert p.max_auto_approve_risk == "none"
        assert p.max_concurrent_agents == 2

    def test_balanced_template(self) -> None:
        p = POLICY_TEMPLATES["balanced"]
        assert p.max_auto_approve_risk == "low"
        assert p.auto_retry_on_failure is True

    def test_aggressive_template(self) -> None:
        p = POLICY_TEMPLATES["aggressive"]
        assert p.max_auto_approve_risk == "medium"
        assert p.max_concurrent_agents == 10


class TestActionAllowed:
    def test_merge_always_forbidden(self) -> None:
        for template in POLICY_TEMPLATES.values():
            assert not is_action_allowed(template, "merge")

    def test_approval_decide_always_forbidden(self) -> None:
        for template in POLICY_TEMPLATES.values():
            assert not is_action_allowed(template, "approval_decide")

    def test_task_write_allowed(self) -> None:
        policy = POLICY_TEMPLATES["balanced"]
        assert is_action_allowed(policy, "task_write")

    def test_read_only_allowed(self) -> None:
        policy = POLICY_TEMPLATES["conservative"]
        assert is_action_allowed(policy, "read_only")


class TestAutoApprove:
    def test_none_never_auto_approves(self) -> None:
        policy = POLICY_TEMPLATES["conservative"]
        assert not can_auto_approve(policy, "read_only")
        assert not can_auto_approve(policy, "task_write")

    def test_low_approves_read_and_task(self) -> None:
        policy = POLICY_TEMPLATES["balanced"]
        assert can_auto_approve(policy, "read_only")
        assert can_auto_approve(policy, "task_write")
        assert not can_auto_approve(policy, "repo_write")

    def test_medium_approves_repo_write(self) -> None:
        policy = POLICY_TEMPLATES["aggressive"]
        assert can_auto_approve(policy, "repo_write")
        assert not can_auto_approve(policy, "pr_open")


class TestLifecycle:
    def test_registered_can_start(self) -> None:
        assert can_transition("registered", "starting")

    def test_registered_can_be_killed(self) -> None:
        assert can_transition("registered", "killed")

    def test_running_can_stop(self) -> None:
        assert can_transition("running", "stopping")

    def test_terminal_cannot_transition(self) -> None:
        for state in TERMINAL_STATES:
            assert not can_transition(state, "running")
            assert not can_transition(state, "starting")

    def test_any_state_can_be_killed(self) -> None:
        for state in ("registered", "starting", "running", "stopping"):
            assert can_transition(state, "killed")


class TestDispatch:
    def test_forbidden_action_denied(self) -> None:
        req = DispatchRequest(
            superintendent_id=uuid4(),
            agent_id=uuid4(),
            ticket_id="t-1",
            project_id=uuid4(),
            action_class="merge",
            risk_level="low",
        )
        result = evaluate_dispatch(req, POLICY_TEMPLATES["aggressive"])
        assert not result.dispatched
        assert result.deny_reason is not None

    def test_auto_approve_low_risk(self) -> None:
        req = DispatchRequest(
            superintendent_id=uuid4(),
            agent_id=uuid4(),
            ticket_id="t-2",
            project_id=uuid4(),
            action_class="task_write",
            risk_level="task_write",
        )
        result = evaluate_dispatch(req, POLICY_TEMPLATES["balanced"])
        assert result.dispatched
        assert not result.needs_human_approval

    def test_high_risk_needs_human(self) -> None:
        req = DispatchRequest(
            superintendent_id=uuid4(),
            agent_id=uuid4(),
            ticket_id="t-3",
            project_id=uuid4(),
            action_class="pr_open",
            risk_level="pr_open",
        )
        result = evaluate_dispatch(req, POLICY_TEMPLATES["balanced"])
        assert result.dispatched
        assert result.needs_human_approval
