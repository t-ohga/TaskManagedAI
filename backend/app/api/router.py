from __future__ import annotations

from fastapi import APIRouter

from backend.app.api import (
    auth,
    claims,
    evidence_items,
    grounding_supports,
    health,
    research_to_ticket,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(claims.router)
api_router.include_router(evidence_items.router)
api_router.include_router(grounding_supports.run_router)
api_router.include_router(grounding_supports.project_router)
api_router.include_router(research_to_ticket.router)
