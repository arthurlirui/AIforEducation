"""API routers."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..data.masterpieces import get_masterpiece, list_masterpieces
from ..schemas import MasterpieceBrief, QuizResult, QuizSubmission
from ..services.assets import ensure_assets

router = APIRouter(tags=["masterpieces"])


@router.get("/masterpieces", response_model=list[MasterpieceBrief])
def api_list_masterpieces():
    return list_masterpieces()


@router.get("/masterpieces/{mid}")
def api_get_masterpiece(mid: str):
    m = get_masterpiece(mid)
    if m is None:
        raise HTTPException(status_code=404, detail=f"masterpiece not found: {mid}")
    assets = ensure_assets(mid)
    payload = {k: v for k, v in m.items() if k != "layers"}
    payload["layers"] = assets.get("layers", [])
    # 测验答案与解析不下发：客户端只能在提交答案后从判分结果获知，
    # 避免通过浏览器 devtools 提前看到正确答案
    payload["quiz"] = [
        {k: v for k, v in q.items() if k not in ("answer", "explain")}
        for q in payload.get("quiz", [])
    ]
    return payload


@router.post("/masterpieces/{mid}/quiz", response_model=QuizResult)
def api_submit_quiz(mid: str, sub: QuizSubmission):
    m = get_masterpiece(mid)
    if m is None:
        raise HTTPException(status_code=404, detail=f"masterpiece not found: {mid}")
    quiz = m["quiz"]
    if len(sub.answers) != len(quiz):
        raise HTTPException(status_code=400, detail=f"expected {len(quiz)} answers, got {len(sub.answers)}")

    per_q = []
    correct = 0
    for i, (q, ans) in enumerate(zip(quiz, sub.answers)):
        ok = ans == q["answer"]
        correct += int(ok)
        per_q.append({"index": i, "correct": ok, "answer": q["answer"], "explain": q["explain"]})
    return QuizResult(
        masterpiece_id=mid,
        total=len(quiz),
        correct=correct,
        score=round(correct / len(quiz), 4),
        per_question=per_q,
    )
