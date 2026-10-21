"""Provider package – each provider implements the same interface."""
from .base import ImageProvider, ProviderRegistry, get_provider  # noqa
from .mock_provider import MockProvider  # noqa
from .pollinations_provider import PollinationsProvider  # noqa
from .openai_provider import OpenAIProvider  # noqa
from .dashscope_provider import DashscopeProvider  # noqa
from .zhipu_provider import ZhipuProvider  # noqa
from .sdwebui_provider import SDWebUIProvider  # noqa


def _register_all() -> None:
    ProviderRegistry.register("mock", MockProvider)
    ProviderRegistry.register("pollinations", PollinationsProvider)
    ProviderRegistry.register("openai", OpenAIProvider)
    ProviderRegistry.register("dashscope", DashscopeProvider)
    ProviderRegistry.register("zhipu", ZhipuProvider)
    ProviderRegistry.register("sdwebui", SDWebUIProvider)


_register_all()
