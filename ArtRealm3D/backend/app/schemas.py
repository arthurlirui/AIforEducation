"""Pydantic schemas (thin — data layer is dict-based)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class MasterpieceBrief(BaseModel):
    id: str
    title: str
    title_en: str
    artist: str
    year: str
    movement: str
    summary: str
    hero_palette: list[str]
    layer_count: int
    chapter_count: int


class ChapterFocus(BaseModel):
    layer: Optional[str] = None
    camera: str = "overview"
    zoom: float = 1.0


class Chapter(BaseModel):
    id: str
    type: str
    title: str
    subtitle: str
    text: str
    focus: ChapterFocus
    duration: int


class QuizQuestion(BaseModel):
    q: str
    options: list[str]
    answer: int
    explain: str


class MasterpieceDetail(BaseModel):
    id: str
    title: str
    title_en: str
    artist: str
    artist_en: str
    year: str
    movement: str
    location: str
    medium: str
    size: str
    summary: str
    hero_palette: list[str]
    layers: list[dict[str, Any]]
    chapters: list[Chapter]
    quiz: list[QuizQuestion]


class QuizSubmission(BaseModel):
    answers: list[int]


class QuizResult(BaseModel):
    masterpiece_id: str
    total: int
    correct: int
    score: float
    per_question: list[dict[str, Any]]
