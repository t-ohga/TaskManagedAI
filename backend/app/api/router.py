from __future__ import annotations

from fastapi import APIRouter

from backend.app.api import auth, claims, evidence_items, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(claims.router)
api_router.include_router(evidence_items.router)
