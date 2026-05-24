from __future__ import annotations

from fastapi import APIRouter

from backend.app.api import (
    audit,
    auth,
    auth_cli,
    claims,
    evidence_items,
    evidence_sources,
    github_webhooks,
    health,
    kpi_rollup,
    me,
    memory,
    p0_acceptance_report,
    research_tasks,
    tickets,
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
api_router.include_router(kpi_rollup.router)
api_router.include_router(p0_acceptance_report.router)
api_router.include_router(tickets.router)
api_router.include_router(memory.router)
api_router.include_router(me.router)
api_router.include_router(audit.router)
