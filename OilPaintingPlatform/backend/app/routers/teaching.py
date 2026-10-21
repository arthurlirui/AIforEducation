from fastapi import APIRouter, HTTPException

from ..schemas import TeachingArticle
from ..services.teaching_service import get_article, list_articles

router = APIRouter(prefix="/teaching", tags=["teaching"])


@router.get("", response_model=list[TeachingArticle])
def get_all_articles() -> list[TeachingArticle]:
    return list_articles()


@router.get("/{article_id}", response_model=TeachingArticle)
def get_one_article(article_id: str) -> TeachingArticle:
    article = get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article '{article_id}' not found")
    return article
