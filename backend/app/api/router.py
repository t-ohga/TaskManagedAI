from __future__ import annotations

from fastapi import APIRouter

from backend.app.api import (
    audit,
    auth,
    auth_cli,
    claims,
    conflict_groups,
    domain_trust,
    eval_analytics,
    evidence_items,
    evidence_source_trust,
    evidence_sources,
    github_webhooks,
    health,
    kpi_rollup,
    me,
    memory,
    onboarding,
    p0_acceptance_report,
    research_advanced,
    research_tasks,
    source_trust,
    tags,
    tickets,
    webhook_events,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(github_webhooks.router)
api_router.include_router(auth.router)
api_router.include_router(auth_cli.router)
api_router.include_router(research_tasks.router)
api_router.include_router(evidence_sources.router)
api_router.include_router(claims.router)
api_router.include_router(evidence_items.router)
api_router.include_router(conflict_groups.router)
api_router.include_router(research_advanced.router)
api_router.include_router(domain_trust.router)
api_router.include_router(evidence_source_trust.router)
api_router.include_router(source_trust.router)
api_router.include_router(kpi_rollup.router)
api_router.include_router(eval_analytics.router)
api_router.include_router(p0_acceptance_report.router)
api_router.include_router(tickets.router)
api_router.include_router(webhook_events.router)
api_router.include_router(tags.router)
api_router.include_router(tags.ticket_tags_router)
api_router.include_router(memory.router)
api_router.include_router(me.router)
api_router.include_router(onboarding.router)
api_router.include_router(audit.router)
