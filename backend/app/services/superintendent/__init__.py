"""Superintendent — AI proxy for human management of TaskManagedAI.

Superintendent is an orchestration actor (NOT approval_decide actor).
Low-risk auto-processing uses Policy Engine auto-allow (SP-024 L0-L3).
merge / deploy / secret_access / provider_call / approval_decide are
always forbidden for Superintendent (hardcoded, not policy-configurable).
"""
