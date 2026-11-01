"""Health router."""
from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}
