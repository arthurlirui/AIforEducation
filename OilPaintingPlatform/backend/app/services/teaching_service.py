"""Service / data loader for teaching articles."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List, Optional

from ..config import DATA_DIR
from ..schemas import TeachingArticle


@lru_cache
def _load() -> Dict[str, TeachingArticle]:
    path = DATA_DIR / "teaching.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: TeachingArticle(**item) for item in raw}


def list_articles() -> List[TeachingArticle]:
    return list(_load().values())


def get_article(article_id: str) -> Optional[TeachingArticle]:
    return _load().get(article_id)
