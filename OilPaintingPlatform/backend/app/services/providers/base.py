"""Provider base class and registry."""
from __future__ import annotations

import abc
import logging
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Type

from ...config import settings
from ...schemas import GeneratedImage

logger = logging.getLogger(__name__)


class ImageProvider(abc.ABC):
    """Abstract image-generation provider."""

    name: str = "base"
    # Metadata for the settings UI
    display_name: str = "Base"
    description: str = ""
    needs_api_key: bool = False
    needs_api_id: bool = False
    needs_base_url: bool = False
    is_free: bool = False
    default_base_url: str = ""
    # Sizes advertised to the frontend for this provider (empty = any)
    supported_sizes: List[str] = []

    def __init__(self, credentials: dict | None = None) -> None:
        self.timeout = settings.request_timeout
        self.credentials = credentials or {}
        # Human-readable notes surfaced to the client via GenerateResponse
        self.notes: List[str] = []
        # Set by get_provider() when the requested provider was unavailable
        # and this mock placeholder was returned instead (None on the
        # normal path), so the response can surface the silent degradation.
        self.fallback_from: Optional[str] = None

    @property
    def api_key(self) -> str:
        return self.credentials.get("api_key", "") or self._env_api_key()

    @property
    def api_id(self) -> str:
        return self.credentials.get("api_id", "") or self._env_api_id()

    @property
    def base_url(self) -> str:
        client_base = (self.credentials.get("base_url") or "").strip()
        if client_base:
            client_key = self.credentials.get("api_key") or ""
            if not client_key and self._env_api_key():
                # Never combine a client-controlled base_url with a
                # server-side (env) API key: that would send the server's
                # key to an arbitrary host. Fall back to the trusted URL.
                logger.warning(
                    "Ignoring client-provided base_url for provider '%s': "
                    "no client api_key supplied while server credentials "
                    "are configured",
                    self.name,
                )
            elif not self._is_safe_base_url(client_base):
                logger.warning(
                    "Ignoring client-provided base_url '%s' for provider "
                    "'%s': scheme must be http/https",
                    client_base,
                    self.name,
                )
            else:
                return client_base
        return self._env_base_url() or self.default_base_url

    @staticmethod
    def _is_safe_base_url(url: str) -> bool:
        """Only http/https URLs with a host are accepted."""
        try:
            parts = urllib.parse.urlsplit(url)
        except ValueError:
            return False
        return parts.scheme in ("http", "https") and bool(parts.netloc)

    def _env_api_key(self) -> str:
        return ""

    def _env_api_id(self) -> str:
        return ""

    def _env_base_url(self) -> str:
        return ""

    @abc.abstractmethod
    def available(self) -> bool:
        """Return True if this provider is configured / reachable."""

    @abc.abstractmethod
    def _generate(
        self,
        prompt: str,
        negative_prompt: str,
        size: str,
        n: int,
    ) -> List[GeneratedImage]:
        """Provider-specific generation logic."""

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        size: Optional[str] = None,
        n: int = 1,
    ) -> List[GeneratedImage]:
        size = size or settings.default_size
        self.notes = []
        return self._generate(prompt, negative_prompt, size, n)

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def save_image_bytes(data: bytes, ext: str = "png") -> Path:
        """Persist image bytes to the output dir and return the path."""
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.{ext}"
        path = settings.output_dir / filename
        path.write_bytes(data)
        return path

    @staticmethod
    def file_url(path: Path) -> str:
        return f"{settings.output_url_prefix}/{path.name}"


class ProviderRegistry:
    _registry: Dict[str, Type[ImageProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: Type[ImageProvider]) -> None:
        cls._registry[name] = provider_cls

    @classmethod
    def names(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def get(cls, name: str, credentials: dict | None = None) -> ImageProvider:
        if name not in cls._registry:
            raise ValueError(
                f"Unknown provider '{name}'. Available: {cls.names()}"
            )
        return cls._registry[name](credentials=credentials)

    @classmethod
    def info(cls) -> List[dict]:
        """Return metadata for all registered providers."""
        result = []
        for name, pcls in cls._registry.items():
            result.append({
                "id": name,
                "name": pcls.display_name,
                "description": pcls.description,
                "needs_api_key": pcls.needs_api_key,
                "needs_api_id": pcls.needs_api_id,
                "needs_base_url": pcls.needs_base_url,
                "free": pcls.is_free,
                "default_base_url": pcls.default_base_url or None,
                "supported_sizes": list(pcls.supported_sizes),
            })
        return result


def get_provider(
    name: Optional[str] = None,
    credentials: dict | None = None,
) -> ImageProvider:
    """Return a provider by name, falling back to the default.

    If the requested provider is unavailable, fall back to ``mock`` so the
    platform always returns something usable in demos. The mock instance
    then carries ``fallback_from`` = the requested name so the response can
    tell the user their choice was silently replaced (instead of leaving
    them wondering why the "model" produces placeholder SVGs).
    """
    target = name or settings.default_provider
    try:
        provider = ProviderRegistry.get(target, credentials=credentials)
        if provider.available():
            return provider
    except ValueError:
        pass
    # Fallback to mock so the UI is always demoable.
    logger.warning(
        "provider '%s' unavailable; falling back to mock placeholder", target
    )
    fallback = ProviderRegistry.get("mock")
    fallback.fallback_from = None if target == "mock" else target
    return fallback
