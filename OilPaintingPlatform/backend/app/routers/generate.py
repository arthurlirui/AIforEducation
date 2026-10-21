import time

from fastapi import APIRouter, HTTPException

from ..schemas import GenerateRequest, GenerateResponse
from ..services.generate_service import generate as do_generate

router = APIRouter(prefix="/generate", tags=["generate"])


@router.post("", response_model=GenerateResponse)
def generate_image(request: GenerateRequest) -> GenerateResponse:
    start = time.time()
    try:
        resp = do_generate(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # provider errors
        raise HTTPException(status_code=502, detail=f"Image generation failed: {e}")
    resp.elapsed_ms = int((time.time() - start) * 1000)
    return resp
