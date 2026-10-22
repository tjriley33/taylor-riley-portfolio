from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Every field maps to env var TAXRAG_<NAME>."""

    model_config = SettingsConfigDict(env_prefix="TAXRAG_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    db_path: Path | None = None  # default: data_dir / "taxrag.sqlite"

    # The tax year the system treats as "current" when a question says nothing.
    current_tax_year: int = 2025

    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    use_cross_encoder: bool = True

    chunk_strategy: str = "hier_v1"
    chunk_max_tokens: int = 450
    chunk_leaf_max_tokens: int = 700

    # Retrieval
    bm25_k: int = 60
    vector_k: int = 60
    rerank_k: int = 30
    context_k: int = 8
    min_relevance: float = 0.75  # reranked final-score floor for "sufficient evidence" (good matches score ~1.3-1.7)

    # LLM (optional). Anthropic by default; Bedrock if llm_provider=bedrock.
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = None
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-5-5"

    # Existing IRS pipeline (upstream source of truth)
    irs_dynamo_table: str = "Forms"
    irs_s3_bucket: str = "forms123456"
    irs_aws_region: str = "us-east-1"
    irs_dynamo_export: Path | None = None  # offline JSON-lines export

    http_user_agent: str = "TaxRAG/0.1 (+research tool; contact owner)"
    http_timeout: float = 90.0

    @property
    def sqlite_path(self) -> Path:
        return self.db_path or (self.data_dir / "taxrag.sqlite")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def model_cache_dir(self) -> Path:
        return self.data_dir / "models"


settings = Settings()
