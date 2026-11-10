import logging
import time

import httpx
from fastapi import APIRouter, HTTPException

from ..schemas import ComposePreviewResponse, GenerateRequest, GenerateResponse
from ..services.generate_service import generate as do_generate
from ..services.prompt_builder import compose_prompt, get_style

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])

# Mounted without the /generate prefix at /api/compose-preview.
preview_router = APIRouter(tags=["generate"])


@router.post("", response_model=GenerateResponse)
def generate_image(request: GenerateRequest) -> GenerateResponse:
    start = time.time()
    try:
        resp = do_generate(request)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        upstream = e.response.status_code
        logger.exception("generate failed: upstream returned %s", upstream)
        if upstream in (401, 403):
            raise HTTPException(status_code=400, detail="API Key 无效或未授权")
        if upstream == 429:
            raise HTTPException(status_code=429, detail="调用过于频繁，请稍后重试")
        if upstream >= 500:
            raise HTTPException(status_code=502, detail="模型服务暂时不可用")
        raise HTTPException(
            status_code=502, detail="模型服务拒绝了本次请求，请调整参数后重试"
        )
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.exception("generate failed: cannot reach model service")
        raise HTTPException(status_code=502, detail="模型服务暂时不可用")
    except Exception:
        logger.exception("generate failed")
        raise HTTPException(status_code=502, detail="图像生成失败，请稍后重试")
    resp.elapsed_ms = int((time.time() - start) * 1000)
    return resp


@preview_router.post("/compose-preview", response_model=ComposePreviewResponse)
def compose_preview(request: GenerateRequest) -> ComposePreviewResponse:
    """Return the exact composed prompt for the given generate parameters,
    so the frontend preview matches what is sent to the model."""
    style = get_style(request.style_id)
    if style is None:
        raise HTTPException(status_code=400, detail=f"Unknown style_id: {request.style_id}")
    composed = compose_prompt(request.prompt, style, request.extra_keywords)
    return ComposePreviewResponse(composed_prompt=composed)
