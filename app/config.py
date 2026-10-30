"""Runtime settings, read from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # LLM: any litellm model string, e.g. "anthropic/claude-sonnet-5-5", "openai/gpt-4o"
    llm_model: str = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-5-5")
    # Empty = omit temperature (provider default, works for every model). A number is sent as-is.
    llm_temperature: str = os.getenv("LLM_TEMPERATURE", "")
    # "live" calls the model; "fake" uses deterministic stubs (tests / offline demo)
    llm_mode: str = os.getenv("LLM_MODE", "live")
    # seconds of simulated latency per model call in LLM_MODE=fake (demos / UI streaming tests)
    demo_delay_s: float = float(os.getenv("DEMO_DELAY_S", "0"))

    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))

    # Sandbox: "docker" (production) or "local" (dev only, NOT isolated)
    sandbox_mode: str = os.getenv("SANDBOX_MODE", "docker")
    sandbox_image: str = os.getenv("SANDBOX_IMAGE", "tahlil-sandbox:latest")
    # Where per-run work dirs are created. When the API itself runs in Docker and launches
    # sandbox containers through the host's docker.sock, this path must be identical on host
    # and in the API container (see docker-compose.yml).
    sandbox_work_dir: str | None = os.getenv("SANDBOX_WORK_DIR") or None
    sandbox_timeout_s: int = int(os.getenv("SANDBOX_TIMEOUT_S", "30"))
    sandbox_memory: str = os.getenv("SANDBOX_MEMORY", "512m")

    max_sql_attempts: int = int(os.getenv("MAX_SQL_ATTEMPTS", "3"))
    max_report_attempts: int = int(os.getenv("MAX_REPORT_ATTEMPTS", "2"))
    max_result_rows: int = int(os.getenv("MAX_RESULT_ROWS", "5000"))

    # --- DB connectors ---
    connector_row_limit: int = int(os.getenv("CONNECTOR_ROW_LIMIT", "200000"))
    connector_max_tables: int = int(os.getenv("CONNECTOR_MAX_TABLES", "30"))
    # comma-separated; empty = any host
    connector_allowed_hosts: frozenset = frozenset(
        h.strip().lower() for h in os.getenv("CONNECTOR_ALLOWED_HOSTS", "").split(",") if h.strip()
    )
    allow_sqlite_connector: bool = os.getenv("ALLOW_SQLITE_CONNECTOR", "false").lower() == "true"

    # --- auth / limits ---
    # comma-separated API keys; empty = auth disabled (local dev)
    api_keys: frozenset = frozenset(k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip())
    asks_per_minute: int = int(os.getenv("ASKS_PER_MINUTE", "10"))
    # Empty = no cap on how many questions run at once. A number is a process-wide slot count.
    max_concurrent_asks: int | None = (
        int(os.environ["MAX_CONCURRENT_ASKS"]) if os.getenv("MAX_CONCURRENT_ASKS", "").strip() else None
    )
    queue_timeout_s: float = float(os.getenv("QUEUE_TIMEOUT_S", "60"))
    # Public demo only: uploaded datasets older than this are deleted. The sample dataset stays.
    demo_retention_hours: float = float(os.getenv("DEMO_RETENTION_HOURS", "24"))
    cors_origins: tuple = tuple(o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip())
    # Public demo: no outbound DB connections, smaller uploads, sample dataset, per-IP limits.
    public_demo: bool = os.getenv("PUBLIC_DEMO", "false").lower() == "true"
    # Empty = no cap. Otherwise USD per UTC day, summed from recorded question costs.
    daily_cost_limit_usd: float | None = (
        float(os.environ["DAILY_COST_LIMIT_USD"]) if os.getenv("DAILY_COST_LIMIT_USD", "").strip() else None
    )
    # Hostnames or IPs of proxies whose X-Forwarded-For is trusted. Anyone else is ignored.
    trusted_proxies: frozenset = frozenset(
        p.strip() for p in os.getenv("TRUSTED_PROXIES", "").split(",") if p.strip()
    )

    use_crewai: bool = field(
        default_factory=lambda: os.getenv("USE_CREWAI", "true").lower() == "true"
    )


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
if settings.sandbox_work_dir:
    Path(settings.sandbox_work_dir).mkdir(parents=True, exist_ok=True)
