"""Pydantic request / response schemas."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class StylePreset(BaseModel):
    id: str
    name: str
    name_en: str
    era: str
    description: str
    prompt_keywords: List[str] = Field(
        default_factory=list,
        description="Keywords appended to the user prompt to enforce style"
    )
    negative_keywords: List[str] = Field(default_factory=list)
    reference_artists: List[str] = Field(default_factory=list)


class ProviderCredentials(BaseModel):
    """Per-provider API credentials sent from the frontend settings panel."""
    api_key: Optional[str] = None
    api_id: Optional[str] = None
    base_url: Optional[str] = None


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="用户提示词")
    style_id: str = Field(..., description="风格 ID")
    provider: Optional[str] = Field(
        None, description="生图模型提供方；留空则使用默认"
    )
    size: Optional[str] = Field(
        None,
        pattern=r"^\d{2,5}x\d{2,5}$",
        description="图像尺寸，格式为 宽x高，如 1024x1024",
    )
    n: int = Field(1, ge=1, le=4, description="生成数量")
    extra_keywords: Optional[str] = Field(
        None, description="用户附加关键词，会拼接到提示词末尾"
    )
    credentials: Optional[ProviderCredentials] = Field(
        None, description="前端传入的 provider 凭据（API Key 等），覆盖 .env 配置"
    )


class GeneratedImage(BaseModel):
    url: str
    provider: str
    revised_prompt: Optional[str] = None
    seed: Optional[int] = None


class GenerateResponse(BaseModel):
    images: List[GeneratedImage]
    composed_prompt: str
    style: StylePreset
    provider: str
    elapsed_ms: int
    notes: List[str] = Field(
        default_factory=list,
        description="给用户的提示信息，如所选模型忽略了某些参数",
    )
    fallback_from: Optional[str] = Field(
        None,
        description="所选 provider 不可用而回退 mock 占位图时，记录原请求的 provider 名；正常路径为 None",
    )


class ComposePreviewResponse(BaseModel):
    composed_prompt: str


class TeachingArticle(BaseModel):
    id: str
    title: str
    category: str
    summary: str
    content: str
    tags: List[str] = Field(default_factory=list)


class GalleryItem(BaseModel):
    id: str
    url: str
    prompt: str
    style_id: str
    style_name: str
    provider: str
    created_at: str


class PromptTemplate(BaseModel):
    id: str
    title: str
    category: str
    prompt: str = Field(..., description="内置提示词模板内容")
    recommended_style: str = Field(..., description="推荐风格 ID")
    description: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str
    default_provider: str
    providers: List[str]


class ProviderInfo(BaseModel):
    id: str
    name: str
    description: str
    needs_api_key: bool
    needs_api_id: bool
    needs_base_url: bool
    free: bool
    default_base_url: Optional[str] = None
    supported_sizes: List[str] = Field(
        default_factory=list,
        description="该 provider 支持的尺寸列表（空表示不限）",
    )
