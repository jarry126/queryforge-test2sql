"""应用配置.

使用 pydantic-settings 统一从环境变量 / .env 加载配置。
所有可调项（模型名、连接串、检索参数、限流、超时）集中在此，便于在不同环境覆盖。
设计原则：换 LLM、改维度、调检索都只动配置，不动代码。
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}
_WEAK_SECRET_VALUES = {"", "queryforge", "postgres", "password", "changeme", "change-me-in-production"}


class Environment(StrEnum):
    """运行环境类型."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """全局配置对象（单例，见 settings）."""

    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    APP_ENV: Environment = Environment.DEVELOPMENT
    PROJECT_NAME: str = "QueryForge Text-to-SQL"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "生产级通用 Text-to-SQL 服务（LangGraph + RAG）"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True
    ALLOWED_ORIGINS: str = "*"
    PUBLIC_QUERY_ENABLED: bool = True

    # ---- LLM ----
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-5.4"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 2000
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 3
    LLM_MAX_CONCURRENCY: int = 5
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # ---- 阿里云百炼 DashScope（embedding + rerank 共用一个 key）----
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_MAX_CONCURRENCY: int = 20  # 并发闸：限制同时打到百炼的请求数，降低触发限流(429)概率

    # ---- Embedding（Qwen text-embedding，OpenAI 兼容接口）----
    EMBEDDING_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIM: int = 1536          # text-embedding-v4 支持 1536；改维度需重建迁移
    EMBEDDING_BATCH_SIZE: int = 10     # DashScope 单次批量上限，超出分批请求

    # ---- Reranker（Qwen gte-rerank，DashScope 原生 API）----
    RERANK_ENABLED: bool = True
    RERANK_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    RERANK_MODEL: str = "gte-rerank-v2"
    RERANK_TOP_N: int = 8

    # ---- PostgreSQL ----
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "queryforge"
    POSTGRES_USER: str = "queryforge"
    POSTGRES_PASSWORD: str = "queryforge"
    POSTGRES_POOL_MIN: int = 2
    POSTGRES_POOL_MAX: int = 20

    # ---- 业务查询库（生产建议使用独立只读账号；默认复用 app postgres 便于本地开发）----
    QUERY_POSTGRES_HOST: str = ""
    QUERY_POSTGRES_PORT: int = 5432
    QUERY_POSTGRES_DB: str = ""
    QUERY_POSTGRES_USER: str = ""
    QUERY_POSTGRES_PASSWORD: str = ""
    QUERY_POSTGRES_POOL_MIN: int = 1
    QUERY_POSTGRES_POOL_MAX: int = 10

    # ---- Redis ----
    REDIS_ENABLED: bool = True
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    CACHE_TTL_SECONDS: int = 600

    # ---- 语义近似缓存（pgvector 相似问命中）----
    # 默认关闭：相似问可能需要不同 SQL，阈值误命中会把别的答案返回给当前问，对 text-to-SQL 风险高。
    # 仅在高并发、可容忍近似的只读场景，且配合"确认正确才缓存"机制时再开启。
    SEMANTIC_CACHE_ENABLED: bool = False
    SEMANTIC_CACHE_THRESHOLD: float = 0.97  # cosine 相似度阈值，越高越严格
    SEMANTIC_CACHE_TTL_SECONDS: int = 3600

    # ---- 熔断器 ----
    CIRCUIT_FAIL_THRESHOLD: int = 5
    CIRCUIT_RESET_SECONDS: float = 30.0

    # ---- RAG ----
    RETRIEVE_TOP_K: int = 20
    RRF_K: int = 60
    QUERY_EXPANSION_ENABLED: bool = False
    DOC_CONTEXT_ENABLED: bool = False
    FEWSHOT_TOP_K: int = 3
    # few-shot 是否跨库检索：单库生产下同库=跨库（无影响）；CSpider 跨域评测需 True 才能激活
    # few-shot（dev 库在 train 索引里没有同库示例）；多租户多库想隔离则设 False。
    FEWSHOT_CROSS_DB: bool = False

    # ---- 关键词检索后端：pg_jieba（同库，默认）| es（Elasticsearch BM25）----
    RETRIEVAL_BACKEND: str = "pg_jieba"
    ES_HOST: str = "localhost"
    ES_PORT: int = 9200
    ES_INDEX_PREFIX: str = "queryforge"

    # ---- Text-to-SQL ----
    SQL_MAX_RETRY: int = 2
    SQL_EXEC_TIMEOUT_SECONDS: int = 10
    SQL_MAX_ROWS: int = 200
    QUERY_MAX_INFLIGHT: int = 20
    QUERY_INFLIGHT_BACKEND: str = "redis"  # redis | local
    QUERY_INFLIGHT_TTL_SECONDS: int = 120
    SQL_DIALECT: str = "sqlite"
    CSPIDER_DB_DIR: str = ""
    HISTORY_TURNS: int = 4
    EVAL_SKIP_ANSWER_LLM: bool = False

    # ---- Langfuse ----
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # ---- 鉴权（JWT）----
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # token 有效期，默认 1 天

    # ---- 入库安全 ----
    INGEST_MAX_CHARS: int = 200_000

    # ---- 限流 ----
    RATE_LIMIT_QUERY: str = "100/second"
    RATE_LIMIT_QUERY_GLOBAL: str = "300/second"
    RATE_LIMIT_DEFAULT: str = "1000/minute"

    # ---- 日志 ----
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_DIR: Path = Path("logs")

    # ---- 评测 ----
    CSPIDER_ROOT: str = ""
    EVAL_LLM_MODEL: str = "gpt-5.4"

    # ---- 派生属性 ----
    @property
    def postgres_dsn(self) -> str:
        """psycopg / asyncpg 通用 DSN。"""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def query_postgres_dsn(self) -> str:
        """业务 SQL 执行库 DSN；非生产未单独配置时复用应用库，方便开发环境。"""
        host = self.QUERY_POSTGRES_HOST or self.POSTGRES_HOST
        port = self.QUERY_POSTGRES_PORT or self.POSTGRES_PORT
        db = self.QUERY_POSTGRES_DB or self.POSTGRES_DB
        user = self.QUERY_POSTGRES_USER or self.POSTGRES_USER
        password = self.QUERY_POSTGRES_PASSWORD or self.POSTGRES_PASSWORD
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == Environment.PRODUCTION

    @model_validator(mode="after")
    def _validate_production_settings(self) -> Settings:
        self._validate_common_settings()
        if not self.is_production:
            return self
        errors = []
        if self.DEBUG:
            errors.append("生产环境必须设置 DEBUG=false")
        if "*" in self.allowed_origins_list:
            errors.append("生产环境必须设置明确的 ALLOWED_ORIGINS，不能使用 *")
        if self.JWT_SECRET == "change-me-in-production" or len(self.JWT_SECRET.encode("utf-8")) < 32:
            errors.append("生产环境 JWT_SECRET 至少 32 字节，且不能使用默认值")
        if self.PUBLIC_QUERY_ENABLED:
            errors.append("生产环境建议设置 PUBLIC_QUERY_ENABLED=false，避免公开单轮查询接口")
        if not self.OPENAI_API_KEY:
            errors.append("生产环境必须显式配置 OPENAI_API_KEY")
        if not self.OPENAI_BASE_URL:
            errors.append("生产环境必须显式配置 OPENAI_BASE_URL")
        if not self.DASHSCOPE_API_KEY:
            errors.append("生产环境必须显式配置 DASHSCOPE_API_KEY，用于 embedding/rerank")
        if self.POSTGRES_HOST in _LOCAL_HOSTS:
            errors.append("生产环境 POSTGRES_HOST 不能使用 localhost/空值")
        if self.POSTGRES_PASSWORD in _WEAK_SECRET_VALUES or len(self.POSTGRES_PASSWORD) < 12:
            errors.append("生产环境 POSTGRES_PASSWORD 必须显式配置强密码")
        if self.REDIS_ENABLED and self.REDIS_HOST in _LOCAL_HOSTS:
            errors.append("生产环境 REDIS_HOST 不能使用 localhost/空值")
        if self.LANGFUSE_ENABLED and (not self.LANGFUSE_PUBLIC_KEY or not self.LANGFUSE_SECRET_KEY):
            errors.append("生产环境启用 Langfuse 时必须配置 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY")
        if self.SQL_DIALECT != "postgres":
            errors.append("生产环境 SQL_DIALECT 必须设置为 postgres，sqlite 仅用于 CSpider/本地评测")
        query_fields = {
            "QUERY_POSTGRES_HOST": self.QUERY_POSTGRES_HOST,
            "QUERY_POSTGRES_DB": self.QUERY_POSTGRES_DB,
            "QUERY_POSTGRES_USER": self.QUERY_POSTGRES_USER,
            "QUERY_POSTGRES_PASSWORD": self.QUERY_POSTGRES_PASSWORD,
        }
        missing_query = [name for name, value in query_fields.items() if not value]
        if missing_query:
            errors.append("生产环境必须显式配置业务只读库: " + ", ".join(missing_query))
        if self.QUERY_POSTGRES_HOST in _LOCAL_HOSTS:
            errors.append("生产环境 QUERY_POSTGRES_HOST 不能使用 localhost/空值")
        if self.QUERY_POSTGRES_PASSWORD in _WEAK_SECRET_VALUES or len(self.QUERY_POSTGRES_PASSWORD) < 12:
            errors.append("生产环境 QUERY_POSTGRES_PASSWORD 必须显式配置强密码")
        if self.QUERY_POSTGRES_HOST == self.POSTGRES_HOST and self.QUERY_POSTGRES_DB == self.POSTGRES_DB:
            errors.append("生产环境业务查询库 QUERY_POSTGRES_* 必须与应用元数据库 POSTGRES_* 隔离")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def _validate_common_settings(self) -> None:
        errors = []
        if self.POSTGRES_POOL_MIN > self.POSTGRES_POOL_MAX:
            errors.append("POSTGRES_POOL_MIN 不能大于 POSTGRES_POOL_MAX")
        if self.QUERY_POSTGRES_POOL_MIN > self.QUERY_POSTGRES_POOL_MAX:
            errors.append("QUERY_POSTGRES_POOL_MIN 不能大于 QUERY_POSTGRES_POOL_MAX")
        if self.SQL_MAX_ROWS <= 0:
            errors.append("SQL_MAX_ROWS 必须大于 0")
        if self.QUERY_MAX_INFLIGHT <= 0:
            errors.append("QUERY_MAX_INFLIGHT 必须大于 0")
        if self.QUERY_INFLIGHT_BACKEND not in {"redis", "local"}:
            errors.append("QUERY_INFLIGHT_BACKEND 只能是 redis 或 local")
        if self.QUERY_INFLIGHT_TTL_SECONDS <= 0:
            errors.append("QUERY_INFLIGHT_TTL_SECONDS 必须大于 0")
        if self.is_production and self.QUERY_INFLIGHT_BACKEND != "redis":
            errors.append("生产环境 QUERY_INFLIGHT_BACKEND 必须使用 redis，确保多实例共享在途并发")
        if self.SQL_EXEC_TIMEOUT_SECONDS <= 0:
            errors.append("SQL_EXEC_TIMEOUT_SECONDS 必须大于 0")
        if self.EMBEDDING_DIM <= 0:
            errors.append("EMBEDDING_DIM 必须大于 0")
        if self.INGEST_MAX_CHARS <= 0:
            errors.append("INGEST_MAX_CHARS 必须大于 0")
        if self.LLM_MAX_CONCURRENCY <= 0:
            errors.append("LLM_MAX_CONCURRENCY 必须大于 0")
        if errors:
            raise ValueError("; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    """返回配置单例（lru_cache 保证全局唯一）。"""
    return Settings()


settings = get_settings()
