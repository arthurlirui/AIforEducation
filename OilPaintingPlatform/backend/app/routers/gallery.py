from fastapi import APIRouter, Query

from ..schemas import GalleryItem
from ..services.generate_service import list_gallery

router = APIRouter(prefix="/gallery", tags=["gallery"])


@router.get("", response_model=list[GalleryItem])
def get_gallery(limit: int = Query(50, ge=1, le=200)) -> list[GalleryItem]:
    items = list_gallery(limit=limit)
    return [GalleryItem(**item) for item in items]
