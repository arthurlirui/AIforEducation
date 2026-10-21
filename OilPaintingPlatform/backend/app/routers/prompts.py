from fastapi import APIRouter, HTTPException, Query

from ..schemas import PromptTemplate
from ..services.prompt_service import get_prompt, list_prompts, categories

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("", response_model=list[PromptTemplate])
def get_all_prompts(
    category: str | None = Query(None, description="按分类筛选"),
) -> list[PromptTemplate]:
    return list_prompts(category=category)


@router.get("/categories", response_model=list[str])
def get_categories() -> list[str]:
    return categories()


@router.get("/{prompt_id}", response_model=PromptTemplate)
def get_one_prompt(prompt_id: str) -> PromptTemplate:
    p = get_prompt(prompt_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' not found")
    return p
