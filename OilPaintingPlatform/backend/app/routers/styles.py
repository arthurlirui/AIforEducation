from fastapi import APIRouter, HTTPException

from ..schemas import StylePreset
from ..services.prompt_builder import get_style, list_styles

router = APIRouter(prefix="/styles", tags=["styles"])


@router.get("", response_model=list[StylePreset])
def get_all_styles() -> list[StylePreset]:
    return list_styles()


@router.get("/{style_id}", response_model=StylePreset)
def get_one_style(style_id: str) -> StylePreset:
    style = get_style(style_id)
    if style is None:
        raise HTTPException(status_code=404, detail=f"Style '{style_id}' not found")
    return style
