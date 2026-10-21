from fastapi import APIRouter

from ..schemas import ProviderInfo
from ..services.providers import ProviderRegistry

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=list[ProviderInfo])
def list_providers() -> list[ProviderInfo]:
    """Return metadata for all registered image-generation providers,
    including whether each needs an API key / base URL."""
    return [ProviderInfo(**info) for info in ProviderRegistry.info()]
