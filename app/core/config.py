from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440
    DATABASE_URL: str = "postgresql+psycopg://engrev:engrev@localhost:5432/engrev"
    CORS_ORIGINS: list[str] = ["http://localhost:4200"]
    LLM_PROVIDER: str = "mock"
    # _2 e _3 são reservas; não há rotação implementada.
    API_KEY: str | None = None
    API_KEY_2: str | None = None
    API_KEY_3: str | None = None
    LLM_MODEL: str = "gemini-3.6-flash"
    LLM_MODEL_LIGHT: str = "gemini-3.5-flash-lite"
    # "en", "pt" ou "none". Nome declarado no código sempre vence.
    NAMING_PLURAL: str = "en"
    # Acima de 1, consolida por maioria ao custo de uma chamada por amostra.
    AMOSTRAS_MODELAGEM: int = 1
    # Limite do modelo, não da aplicação.
    MAX_OUTPUT_TOKENS: int = 64000
    MAX_OUTPUT_TOKENS_LIGHT: int = 8000
    MAX_UPLOAD_SIZE_MB: int = 20
    TOKEN_BUDGET: int = 200000
    # Na unidade de `estimate_tokens` (len//4), não em tokens reais.
    EVIDENCE_BUDGET: int = 90000
    MAP_BUDGET: int = 40000
    SIMULATE_PROGRESS: bool = False
    PROGRESS_STAGE_DELAY_SECONDS: float = 1.5
    SEED_ADMIN_EMAIL: str = "admin@engrev.dev"
    SEED_ADMIN_PASSWORD: str = "admin123"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
