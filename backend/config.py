from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    cors_origins: str = "*"
    database_url: str = "sqlite+aiosqlite:///./app.db"
    storage_backend: str = "local"
    local_upload_dir: str = "./uploads"
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_bucket: str = "evidence-files"
    rag_backend: str = "memory"

    gemini_api_key: str = ""
    groq_api_key: str = ""
    tavily_api_key: str = ""
    opensanctions_api_key: str = ""

    gemini_model: str = "gemini-3.8-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    groq_model: str = "qwen/qwen3.8-27b"
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 5

    whed_url: str = "https://whed.net/results_institutions.php"
    secp_search_url: str = "https://eservices.secp.gov.pk/eServices/NameSearch.jsp"

    app_secret: str = "change-me"

    # Per-call timeouts so one slow external source can never hang the whole
    # verification run. asyncio.gather() runs sources concurrently, but
    # without an explicit per-call timeout a single hung call still blocks
    # the gather() indefinitely.
    llm_call_timeout_seconds: float = 25.0
    web_research_call_timeout_seconds: float = 15.0

    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        """
        Parses CORS_ORIGINS into a list. Comma-separated, e.g.
        "https://verifyabroad.up.railway.app,https://verifyabroad.vercel.app".
        Defaults to "*" for local dev convenience only - always set this
        explicitly to the real frontend origin(s) in production.
        """
        raw = self.cors_origins.strip()
        if raw == "*" or not raw:
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


settings = Settings()
