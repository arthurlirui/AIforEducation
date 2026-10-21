from fastapi import APIRouter

from ..schemas import HealthResponse
from ..config import settings
from ..services.providers import ProviderRegistry

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        default_provider=settings.default_provider,
        providers=ProviderRegistry.names(),
    )
