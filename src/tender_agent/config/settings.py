from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM 配置
    DEFAULT_LLM_PROVIDER: str = "token_plan"
    DEFAULT_MODEL_NAME: str = "claude-3-5-sonnet-20241022"
    ENABLE_CONTENT_REWRITE: bool = False
    CONTENT_MAX_CONCURRENCY: int = 3
    CONTENT_BATCH_SIZE: int = 2
    CONTENT_MAX_TOKENS: int = 1200
    LLM_REQUEST_TIMEOUT_SECONDS: float = 240.0
    TITLE_LLM_TIMEOUT_SECONDS: float = 60.0
    MATERIAL_MAPPER_USE_LLM: bool = True
    MATERIAL_MAPPER_LLM_TIMEOUT_SECONDS: float = 90.0
    MATERIAL_MAPPER_BATCH_SIZE: int = 6
    MATERIAL_MAPPER_CONCURRENCY: int = 3

    # LangSmith 配置
    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "Tender-Agent-V1"

    # 火山引擎配置
    VOLCENGINE_API_KEY: str = ""
    VOLCENGINE_BASE_URL: str = ""
    VOLCENGINE_MODEL_NAME: str = ""

    # 阿里云百炼 / DashScope OpenAI 兼容接口
    BAILIAN_API_KEY: str = ""
    BAILIAN_BASE_URL: str = "https://coding.dashscope.aliyuncs.com/v1"
    BAILIAN_MODEL_NAME: str = "qwen3.6-plus"

    # 阿里云 Token Plan / MaaS OpenAI 兼容接口
    TOKEN_PLAN_API_KEY: str = ""
    TOKEN_PLAN_BASE_URL: str = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    TOKEN_PLAN_MODEL_NAME: str = "qwen3.6-plus"

    # Cost estimation (USD per 1M tokens)
    COST_VOLCENGINE_INPUT_PER_M: float = 0.8
    COST_VOLCENGINE_OUTPUT_PER_M: float = 2.0
    COST_BAILIAN_INPUT_PER_M: float = 0.8
    COST_BAILIAN_OUTPUT_PER_M: float = 2.0
    COST_ANTHROPIC_INPUT_PER_M: float = 3.0
    COST_ANTHROPIC_OUTPUT_PER_M: float = 15.0

    # API Keys
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Database
    DATABASE_URL: str = ""
    DB_CONNECT_TIMEOUT_SECONDS: int = 5
    DB_POOL_TIMEOUT_SECONDS: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8-sig"
        extra = "ignore"

settings = Settings()
