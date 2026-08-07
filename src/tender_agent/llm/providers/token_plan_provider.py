"""阿里云 Token Plan / MaaS OpenAI 兼容 Provider。"""

from ...config.settings import settings
from .bailian_provider import BailianProvider


class TokenPlanProvider(BailianProvider):
    """Token Plan OpenAI-compatible provider using the shared Bailian JSON parser."""

    def __init__(self):
        super().__init__(
            api_key=settings.TOKEN_PLAN_API_KEY,
            base_url=settings.TOKEN_PLAN_BASE_URL,
            model_name=settings.TOKEN_PLAN_MODEL_NAME,
            provider_label="TOKEN_PLAN",
        )
